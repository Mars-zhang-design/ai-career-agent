"""Offline frontend interaction and HTTP adapter tests; no real accounts or writes."""
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import httpx
from streamlit.testing.v1 import AppTest
from web_client import ApiError, request_api

APP = str(Path(__file__).resolve().parents[1] / "web_app.py")
RESULT = {"task_id":"test-task", "status":"success", "saved":False, "steps":3,
          "analysis":{"match_score":60,"matched_skills":["Python"],"missing_skills":["RAG"],"warnings":[]},
          "optimization":None, "warnings":[],"errors":[]}


def button(app, label):
    return next(item for item in app.button if item.label == label)


class WebTests(unittest.TestCase):
    def app(self, logged_in=False):
        app=AppTest.from_file(APP, default_timeout=15)
        if logged_in:
            app.session_state["token"]="test-token"
            app.session_state["user_name"]="测试用户"
        return app.run()

    def test_login_empty_inputs_do_not_call_service(self):
        app=self.app()
        with patch('web_client.request_api') as api:
            button(app,'登录工作台').click().run()
        api.assert_not_called()
        self.assertTrue(app.error)
        self.assertFalse(app.exception)

    def test_login_opens_workspace_without_showing_token(self):
        app=self.app()
        app.text_input(key='login_email').set_value('test@example.invalid')
        app.text_input(key='login_password').set_value('test-password')
        with patch('web_client.request_api',return_value={'access_token':'private-test-token','name':'测试用户'}):
            button(app,'登录工作台').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['token'],'private-test-token')
        self.assertTrue(button(app,'开始处理').disabled)
        self.assertNotIn('private-test-token',str([m.value for m in app.markdown]))

    def prepare(self):
        app=self.app(True)
        app.text_area(key='resume_text').set_value('真实经历测试文本').run()
        with patch('web_client.request_api',return_value={'id':2}):
            button(app,'保存简历').click().run()
        app.text_input(key='company').set_value('测试公司')
        app.text_input(key='job_title').set_value('测试职位')
        app.text_area(key='jd_text').set_value('岗位要求测试文本').run()
        with patch('web_client.request_api',return_value={'id':5}):
            button(app,'保存岗位').click().run()
        return app

    def test_save_run_and_edit_invalidation(self):
        app=self.prepare()
        self.assertFalse(app.exception)
        self.assertFalse(button(app,'开始处理').disabled)
        with patch('web_client.request_api',return_value=RESULT) as api:
            button(app,'开始处理').click().run()
        payload=api.call_args.kwargs['data']
        self.assertEqual((payload['resume_id'],payload['job_description_id']),(2,5))
        self.assertEqual(payload['mode'],'analyze')
        self.assertEqual(app.metric[0].value,'60 / 100')
        self.assertFalse(app.exception)
        app.text_area(key='resume_text').set_value('修改过的经历').run()
        self.assertTrue(button(app,'开始处理').disabled)
        self.assertTrue(any('上一次' in x.value for x in app.warning))

    def test_failed_task_retains_analysis_without_success_banner(self):
        app=self.prepare()
        failure={**RESULT,'status':'error','errors':[{'message':'未产生有效改写'}]}
        with patch('web_client.request_api',side_effect=ApiError('未产生有效改写',502,failure)):
            button(app,'开始处理').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertEqual(app.metric[0].value,'60 / 100')
        self.assertFalse(any('处理完成' in x.value for x in app.success))

    def test_session_expiration_clears_user_data(self):
        app=self.app(True)
        app.text_area(key='resume_text').set_value('private draft').run()
        with patch('web_client.request_api',side_effect=ApiError('expired',401)):
            button(app,'保存简历').click().run()
        self.assertFalse(app.exception)
        self.assertNotIn('token',app.session_state)
        self.assertNotIn('resume_text',app.session_state)
        self.assertTrue(button(app,'登录工作台'))

    def test_logout_clears_results_and_identity(self):
        app=self.app(True)
        app.session_state['result']=RESULT
        button(app,'退出登录').click().run()
        self.assertNotIn('token',app.session_state)
        self.assertNotIn('result',app.session_state)
        self.assertFalse(app.exception)

    def test_optimization_renders_comparison_and_download(self):
        app=self.app(True)
        app.session_state['result']={**RESULT,'saved':True,'optimization':{
            'optimized_resume':'实际改写后的测试文本',
            'rewrite_suggestions':[{'original':'原句','optimized':'改写后的句子',
                'issue':'表达冗余','reason':'突出实际职责','evidence':['原句'],'jd_evidence':'岗位要求原文'}]}}
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any('改写后的句子' == x.value for x in app.markdown))
        self.assertTrue(any('突出实际职责' in x.value for x in app.markdown))
        self.assertTrue(any('岗位要求原文' in x.value for x in app.markdown))
        self.assertTrue(any(x.value == '原句' for x in app.text))
        self.assertEqual(app.code[0].value,'实际改写后的测试文本')
        self.assertEqual(len(app.get('download_button')),1)


class ClientTests(unittest.TestCase):
    def test_server_error_body_is_retained(self):
        response=httpx.Response(502,json={'task_id':'test','errors':[{'message':'保存未确认'}]})
        with patch('web_client.httpx.Client') as cls:
            cls.return_value.__enter__.return_value.request.return_value=response
            with self.assertRaises(ApiError) as caught:
                request_api('POST','/resume/agent-by-id',token='secret',data={})
        self.assertEqual(caught.exception.payload['task_id'],'test')
        self.assertEqual(str(caught.exception),'保存未确认')

    def test_timeout_does_not_retry_writes(self):
        with patch('web_client.httpx.Client') as cls:
            request=cls.return_value.__enter__.return_value.request
            request.side_effect=httpx.ReadTimeout('private payload')
            with self.assertRaises(ApiError) as caught:
                request_api('POST','/resumes',data={})
            request.assert_called_once()
        self.assertNotIn('private payload',str(caught.exception))


if __name__ == '__main__':
    unittest.main()
