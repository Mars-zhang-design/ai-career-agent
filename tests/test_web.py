"""Offline frontend interaction and HTTP adapter tests; no real accounts or writes."""
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from streamlit.testing.v1 import AppTest
from web_client import ApiError, request_api

APP = str(Path(__file__).resolve().parents[1] / "web_app.py")


def button(app, label):
    return next(item for item in app.button if item.label == label)


def career_envelope():
    # Local import avoids coupling frontend module initialization to API fixtures.
    from test_career import report
    value = report().model_dump()
    value.update(score=60, evidence_coverage=40)
    return {"report": value, "report_token": "opaque-test-token",
            "history_saved": True, "history_id": 10}


class WebTests(unittest.TestCase):
    def app(self, logged_in=False):
        app = AppTest.from_file(APP, default_timeout=15)
        if logged_in:
            app.session_state["token"] = "test-token"
            app.session_state["user_name"] = "测试用户"
        return app.run()

    def test_login_empty_inputs_do_not_call_service(self):
        app = self.app()
        with patch('web_client.request_api') as api:
            button(app, '登录工作台').click().run()
        api.assert_not_called()
        self.assertTrue(app.error)
        self.assertFalse(app.exception)

    def test_login_opens_workspace_without_showing_token(self):
        app = self.app()
        app.text_input(key='login_email').set_value('test@example.invalid')
        app.text_input(key='login_password').set_value('test-password')
        with patch('web_client.request_api', return_value={'access_token': 'private-test-token', 'name': '测试用户'}):
            button(app, '登录工作台').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['token'], 'private-test-token')
        self.assertTrue(button(app, '分析岗位与能力差距').disabled)
        self.assertNotIn('private-test-token', str([m.value for m in app.markdown]))

    def prepare(self):
        app = self.app(True)
        app.text_area(key='resume_text').set_value('真实经历测试文本').run()
        with patch('web_client.request_api', return_value={'id': 2}):
            button(app, '保存简历').click().run()
        app.text_input(key='company').set_value('测试公司')
        app.text_input(key='job_title').set_value('测试职位')
        app.text_area(key='jd_text').set_value('岗位要求测试文本').run()
        with patch('web_client.request_api', return_value={'id': 5}):
            button(app, '保存岗位').click().run()
        return app

    def test_saved_sources_are_analyzed_and_edited_sources_invalidate_old_report(self):
        app = self.prepare()
        self.assertFalse(button(app, '分析岗位与能力差距').disabled)
        with patch('web_client.request_api', return_value=career_envelope()) as api:
            button(app, '分析岗位与能力差距').click().run()
        api.assert_called_once_with('POST', '/career/review', token='test-token',
                                    data={'resume_id': 2, 'job_description_id': 5})
        self.assertTrue(any(m.label == '岗位证据匹配度' and m.value == '60 / 100' for m in app.metric))
        self.assertFalse(app.exception)
        app.text_area(key='resume_text').set_value('修改过的经历').run()
        self.assertFalse(button(app, '分析岗位与能力差距').disabled)
        self.assertTrue(any('资料已修改' in x.value for x in app.warning))
        self.assertFalse(any(m.label == '岗位证据匹配度' for m in app.metric))
        self.assertFalse(app.chat_input)

    def test_analysis_failure_does_not_claim_success_or_store_legacy_error_payload(self):
        app = self.prepare()
        payload = {'task_id': 'old-agent-shaped-error', 'analysis': {'match_score': 99}}
        with patch('web_client.request_api', side_effect=ApiError('岗位分析暂未完成', 502, payload)):
            button(app, '分析岗位与能力差距').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('岗位分析暂未完成' in x.value for x in app.error))
        self.assertNotIn('career', app.session_state)
        self.assertNotIn('result', app.session_state)
        self.assertFalse(app.metric)
        self.assertFalse(app.success)

    def test_retry_after_failed_analysis_reuses_auto_saved_sources(self):
        app = self.app(True)
        app.text_area(key='resume_text').set_value('真实经历测试文本')
        app.text_area(key='jd_text').set_value('岗位要求测试文本').run()
        self.assertFalse(button(app, '分析岗位与能力差距').disabled)
        with patch('web_client.request_api', side_effect=[{'id': 2}, {'id': 5}, ApiError('稍后重试', 502)]) as api:
            button(app, '分析岗位与能力差距').click().run()
        self.assertEqual([c.args[1] for c in api.call_args_list], ['/resumes', '/job-descriptions', '/career/review'])
        self.assertEqual(app.session_state['resume_id'], 2)
        self.assertEqual(app.session_state['job_description_id'], 5)
        with patch('web_client.request_api', return_value=career_envelope()) as retry:
            button(app, '分析岗位与能力差距').click().run()
        self.assertEqual([c.args[1] for c in retry.call_args_list], ['/career/review'])
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state['career']['history_saved'])

    def test_session_expiration_clears_user_data(self):
        app = self.app(True)
        app.text_area(key='resume_text').set_value('private draft').run()
        with patch('web_client.request_api', side_effect=ApiError('expired', 401)):
            button(app, '保存简历').click().run()
        self.assertFalse(app.exception)
        self.assertNotIn('token', app.session_state)
        self.assertNotIn('resume_text', app.session_state)
        self.assertTrue(button(app, '登录工作台'))

    def test_logout_clears_results_and_identity(self):
        app = self.app(True)
        app.session_state['career'] = career_envelope()
        app.session_state['result'] = {'status': 'success', 'optimization': {'optimized_resume': 'private old result'}}
        button(app, '退出登录').click().run()
        self.assertNotIn('token', app.session_state)
        self.assertNotIn('career', app.session_state)
        self.assertNotIn('result', app.session_state)
        self.assertFalse(app.exception)

    def test_workspace_focuses_on_gap_flow_without_polish_or_legacy_agent_controls(self):
        app = self.prepare()
        with patch('web_client.request_api', return_value=career_envelope()):
            button(app, '分析岗位与能力差距').click().run()
        self.assertEqual([tab.label for tab in app.tabs], ['① 对照岗位', '② 看清差距', '③ 目标清单'])
        labels = {item.label for item in app.button}
        for removed in ('美化当前简历', '生成目标简历预览', '开始处理'):
            self.assertNotIn(removed, labels)
        self.assertFalse(any(item.key == 'mode_label' for item in app.radio))
        self.assertTrue(button(app, '生成 / 更新行动计划'))
        self.assertTrue(app.chat_input)
        self.assertFalse(app.exception)

    def test_stale_legacy_results_are_not_displayed_in_workspace(self):
        app = self.app(True)
        private_text = '旧改写结果只应在历史记录中查看'
        app.session_state['result'] = {'status': 'success', 'saved': True, 'steps': 3,
            'analysis': {'match_score': 99, 'matched_skills': [], 'missing_skills': [], 'warnings': []},
            'optimization': {'optimized_resume': private_text, 'rewrite_suggestions': []},
            'warnings': [], 'errors': []}
        app.session_state['career_polish'] = {'context': ({'resume_text': ''}, {'company': '', 'job_title': '', 'jd_text': ''}),
            'data': {'optimization': {'optimized_resume': private_text}}}
        app.run()
        rendered = '\n'.join(str(item.value) for kind in ('text', 'markdown', 'code') for item in app.get(kind))
        self.assertNotIn(private_text, rendered)
        self.assertFalse(app.metric)
        self.assertFalse(app.get('download_button'))
        self.assertFalse(app.exception)


class AutomaticPlanningUiTests(unittest.TestCase):
    app=WebTests.app
    prepare=WebTests.prepare

    def test_auto_plan_preserves_review_and_manual_retry_does_not_reanalyze(self):
        app=self.prepare()
        self.assertFalse(app.checkbox(key='auto_plan').value)
        app.checkbox(key='auto_plan').set_value(True).run()
        reviewed=career_envelope()
        with patch('web_client.request_api',side_effect=[reviewed,ApiError('计划暂时失败',502)]) as api:
            button(app,'分析岗位与能力差距').click().run()
        self.assertEqual([c.args[1] for c in api.call_args_list], ['/career/review','/career/advance'])
        self.assertEqual(app.session_state['career'],reviewed)
        self.assertTrue(any('分析结果已保留' in item.value for item in app.warning))
        self.assertFalse(app.exception)
        with patch('web_client.request_api') as api:
            app.run()
        api.assert_not_called()
        planned=career_envelope()
        planned['report']['tasks']=[dict(requirement_id='r1', objective='实践验证', actions=['实现接口'],
            deliverable='测试报告', acceptance=['测试通过'], references=[], reference_status='uncited')]
        with patch('web_client.request_api',return_value=planned) as api:
            button(app,'生成 / 更新行动计划').click().run()
        self.assertEqual([c.args[1] for c in api.call_args_list], ['/career/advance'])
        self.assertEqual(api.call_args.kwargs['data'], {'report_token':reviewed['report_token'],'skip_clarification':True})
        self.assertNotIn('workflow_result',app.session_state)
        self.assertFalse(app.exception)

    def test_auto_plan_success_navigates_to_checklist_without_false_save_claim(self):
        app=self.prepare();app.checkbox(key='auto_plan').set_value(True).run()
        planned=career_envelope();planned['history_saved']=False
        planned['report']['tasks']=[dict(requirement_id='r1', objective='实践验证', actions=['实现接口'],
            deliverable='测试报告', acceptance=['测试通过'], references=[], reference_status='uncited')]
        with patch('web_client.request_api',side_effect=[career_envelope(),planned]):
            button(app,'分析岗位与能力差距').click().run()
        self.assertEqual(app.session_state['workspace_default_tab'],'③ 目标清单')
        self.assertTrue(any('尚未确认保存' in w.value for w in app.warning))
        self.assertFalse(any('已保存' in item.value for item in app.success))
        self.assertFalse(app.exception)

    def test_waiting_agent_opens_clarification_and_refresh_does_not_call_api(self):
        app=self.prepare()
        self.assertEqual(app.checkbox(key='auto_plan').label, '分析后帮我安排下一步')
        app.checkbox(key='auto_plan').set_value(True).run()
        waiting=career_envelope()
        waiting['report_token']='waiting-token'
        waiting['report']['agent']={'enabled':True,'status':'waiting','note':'先核对这段经历，再安排练习。'}
        waiting['report']['messages']=[{'role':'assistant','content':'你是否独立做过接口鉴权？'}]
        with patch('web_client.request_api',side_effect=[career_envelope(),waiting]) as api:
            button(app,'分析岗位与能力差距').click().run()
        self.assertEqual([c.args[1] for c in api.call_args_list], ['/career/review','/career/advance'])
        self.assertEqual(app.session_state['career'], waiting)
        self.assertEqual(app.session_state['workspace_default_tab'],'② 看清差距')
        self.assertTrue(app.chat_input)
        self.assertTrue(any('接口鉴权' in m.value for m in app.markdown))
        self.assertFalse(app.exception)
        with patch('web_client.request_api') as idle:
            app.run()
        idle.assert_not_called()

    def test_failed_agent_result_remains_visible_and_can_retry_without_review(self):
        app=self.prepare();app.checkbox(key='auto_plan').set_value(True).run()
        failed=career_envelope();failed['report_token']='failed-token'
        failed['report']['agent']={'enabled':True,'status':'failed','note':'资料服务暂不可用，稍后可继续。'}
        with patch('web_client.request_api',side_effect=[career_envelope(),failed]) as api:
            button(app,'分析岗位与能力差距').click().run()
        self.assertEqual(app.session_state['career'], failed)
        self.assertTrue(any('资料服务暂不可用' in w.value for w in app.warning))
        self.assertTrue(any(m.label=='岗位证据匹配度' for m in app.metric))
        self.assertFalse(app.exception)
        completed=career_envelope()
        completed['report']['agent']={'enabled':True,'status':'complete','note':'下一步已安排。'}
        with patch('web_client.request_api',return_value=completed) as retry:
            button(app,'生成 / 更新行动计划').click().run()
        retry.assert_called_once_with('POST','/career/advance',token='test-token',
            data={'report_token':'failed-token','skip_clarification':True})
        self.assertEqual(app.session_state['career'],completed)
        self.assertFalse(app.exception)


class ClientTests(unittest.TestCase):
    def test_server_error_body_is_retained(self):
        response = httpx.Response(502, json={'task_id': 'test', 'errors': [{'message': '保存未确认'}]})
        with patch('web_client.httpx.Client') as cls:
            cls.return_value.__enter__.return_value.request.return_value = response
            with self.assertRaises(ApiError) as caught:
                request_api('POST', '/resume/agent-by-id', token='secret', data={})
        self.assertEqual(caught.exception.payload['task_id'], 'test')
        self.assertEqual(str(caught.exception), '保存未确认')

    def test_timeout_does_not_retry_writes(self):
        with patch('web_client.httpx.Client') as cls:
            request = cls.return_value.__enter__.return_value.request
            request.side_effect = httpx.ReadTimeout('private payload')
            with self.assertRaises(ApiError) as caught:
                request_api('POST', '/resumes', data={})
            request.assert_called_once()
        self.assertNotIn('private payload', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
