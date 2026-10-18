"""Exercise the new tabbed workflow without network or private data."""
import unittest
from unittest.mock import patch
from pathlib import Path
from streamlit.testing.v1 import AppTest
from test_career import report
from test_web import button

APP=str(Path(__file__).resolve().parents[1]/'web_app.py')


def envelope():
    value=report().model_dump()
    value['messages']=[{'role':'assistant','content':'你做过哪些后端功能？'}]
    return {'report':value,'report_token':'opaque-test-token'}


class CareerUiTests(unittest.TestCase):
    def app(self):
        app=AppTest.from_file(APP,default_timeout=15)
        app.session_state['token']='test-token'
        app.session_state['user_name']='测试用户'
        app.session_state['resume_text']='测试简历'
        app.session_state['company']='测试公司'
        app.session_state['job_title']='测试岗位'
        app.session_state['jd_text']='测试岗位要求'
        app.session_state['resume_id']=2
        app.session_state['job_description_id']=5
        context=({'resume_text':'测试简历'},{'company':'测试公司','job_title':'测试岗位','jd_text':'测试岗位要求'})
        app.session_state['saved_resume']=context[0]
        app.session_state['saved_job']=context[1]
        app.session_state['career_context']=context
        app.session_state['career']=envelope()
        return app.run()

    def test_all_panels_render_and_scoring_is_explained(self):
        app=self.app()
        self.assertFalse(app.exception)
        self.assertTrue(any('岗位证据匹配度' == m.label for m in app.metric))
        self.assertEqual(len(app.chat_input),1)
        self.assertTrue(button(app,'生成 / 更新行动计划'))
        labels={b.label for b in app.button}
        self.assertTrue(labels.isdisjoint({'美化当前简历','生成目标简历预览','开始处理','另存包含这些经历的简历'}))
        self.assertEqual([t.label for t in app.tabs], ['① 对照岗位','② 看清差距','③ 目标清单'])

    def test_chat_response_is_displayed_without_auto_confirming(self):
        app=self.app()
        reply=envelope();reply['report']['messages'].append({'role':'user','content':'我实际做过后端接口'})
        reply['report']['messages'].append({'role':'assistant','content':'请确认补充经历'})
        reply['report']['pending']=[{'requirement_id':'r1','status':'supported','statement':'我实际做过后端接口','reason':'自述'}]
        with patch('web_client.request_api',return_value=reply) as api:
            app.chat_input[0].set_value('我实际做过后端接口').run()
        self.assertEqual(api.call_args.args[1],'/career/chat')
        self.assertEqual(app.session_state['career']['report']['score'],0)
        self.assertTrue(button(app,'准确，确认更新'))
        self.assertFalse(app.exception)

    def test_confirm_updates_report_then_clears_stale_target(self):
        app=self.app();value=envelope()
        value['report']['pending']=[{'requirement_id':'r1','status':'supported','statement':'我实际做过后端接口','reason':'自述'}]
        app.session_state['career']=value
        app.session_state['target_resume']={'text':'old target','pending_count':3}
        app.run()
        updated=envelope();updated['report']['score']=43
        with patch('web_client.request_api',return_value=updated):
            button(app,'准确，确认更新').click().run()
        self.assertEqual(app.session_state['career']['report']['score'],43)
        self.assertNotIn('target_resume',app.session_state)
        self.assertFalse(app.exception)

    def test_checklist_automatically_appears_without_extra_api_call(self):
        with patch('web_client.request_api') as api:
            app=self.app()
        api.assert_not_called()
        self.assertTrue(any('清单不自动修改简历' in item.value for item in app.caption))
        self.assertTrue(any(b.label=='下载目标清单' for b in app.get('download_button')))
        self.assertFalse(app.exception)

    def test_changed_input_blocks_old_conversation(self):
        app=self.app()
        app.text_area(key='resume_text').set_value('已修改的新简历').run()
        self.assertEqual(len(app.chat_input),0)
        self.assertFalse(button(app,'分析岗位与能力差距').disabled)
        self.assertFalse(app.exception)

    def test_review_button_uses_saved_ids(self):
        app=self.app()
        with patch('web_client.request_api',return_value=envelope()) as api:
            button(app,'分析岗位与能力差距').click().run()
        self.assertEqual(api.call_args.args[1],'/career/review')
        self.assertEqual(api.call_args.kwargs['data'],{'resume_id':2,'job_description_id':5})
        self.assertFalse(app.exception)


    def test_plan_shows_references_personal_evidence_and_export(self):
        app=self.app()
        value=envelope()
        value['report']['tasks']=[{
            'requirement_id':'r1', 'objective':'练习接口', 'actions':['添加校验'],
            'deliverable':'代码', 'acceptance':['错误输入可处理'], 'reference_status':'cited',
            'references':[{'id':'ref1','title':'Python 官方教程',
                'source_url':'https://docs.python.org/3/tutorial/', 'excerpt':'模块和异常处理。',
                'source':'python.md','updated_at':'2026-10-18'}]}]
        with patch('web_client.request_api',return_value=value) as api:
            button(app,'生成 / 更新行动计划').click().run()
        self.assertEqual(api.call_args.args[1],'/career/advance')
        self.assertEqual(api.call_args.kwargs['data'],{'report_token':'opaque-test-token','skip_clarification':True})
        self.assertFalse(app.exception)
        self.assertTrue(any(e.label=='学习参考：Python 官方教程' for e in app.expander))
        self.assertTrue(any(t.value=='模块和异常处理。' for t in app.text))
        self.assertTrue(any('尚未确认缺失' in item.value for item in app.info))
        from career_ui import plan_export
        exported=plan_export(value['report'])
        self.assertIn('https://docs.python.org/3/tutorial/',exported)
        self.assertIn('岗位原文：',exported)
        self.assertIn('不是已完成经历',exported)
        self.assertIn('模块和异常处理。',exported)

    def test_plan_retrieval_failure_is_visible(self):
        app=self.app(); value=envelope()
        value['report']['tasks']=[{'requirement_id':'r1', 'objective':'练习', 'actions':['实现'],
            'deliverable':'代码', 'acceptance':['通过测试'], 'references':[], 'reference_status':'unavailable'}]
        app.session_state['career']=value
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any('知识检索不可用' in w.value and '未引用资料' in w.value for w in app.warning))


    def test_target_cards_counts_and_filter(self):
        app=self.app(); value=envelope();value['report']['requirements'][0]['status']='gap'
        app.session_state['career']=value;app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(m.label=='目标事项' and m.value=='3' for m in app.metric))
        self.assertTrue(any(m.label=='待完成' and m.value=='1' for m in app.metric))
        self.assertTrue(any(e.label=='分析依据：原简历与已确认经历' for e in app.expander))
        self.assertEqual(len([e for e in app.expander if e.label=='查看岗位依据与待确认内容']),3)
        app.radio(key='target_status_filter').set_value('待完成').run()
        self.assertFalse(app.exception)
        self.assertEqual(len([e for e in app.expander if e.label=='查看岗位依据与待确认内容']),1)
        app.radio(key='target_status_filter').set_value('待确认').run()
        self.assertEqual(len([e for e in app.expander if e.label=='查看岗位依据与待确认内容']),2)

    def test_empty_target_is_explicit(self):
        app=self.app();value=envelope()
        for row in value['report']['requirements']: row['status']='supported'
        app.session_state['career']=value;app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any('当前没有待完成' in item.value for item in app.success))
        self.assertTrue(button(app,'生成 / 更新行动计划').disabled)


    def test_target_export_groups_statuses_and_keeps_facts_separate(self):
        from target_preview import build_target_preview, export_target_checklist
        r=report();r.requirements[0].status='partial'
        result=build_target_preview(r,'仅原简历经历')
        result['text']='旧缓存文本'
        exported=export_target_checklist(result)
        self.assertIn('待完成：1 项    待确认：2 项',exported)
        self.assertIn('三、待完成事项（1 项）',exported)
        self.assertIn('四、待确认事项（2 项）',exported)
        completed=exported.split('三、待完成事项')[1].split('四、待确认事项')[0]
        pending=exported.split('四、待确认事项')[1]
        self.assertIn('【部分满足 · 待完成】Python',completed)
        self.assertNotIn('【待确认】',completed)
        self.assertIn('【待确认】RAG',pending)
        self.assertNotIn('仅原简历经历',pending)
        self.assertIn('非投递版',exported)
        self.assertNotIn('旧缓存文本',exported)


    def test_obsolete_result_cache_is_not_shown(self):
        app=self.app()
        app.session_state['career_polish']={'context':app.session_state['career_context'],
            'data':{'saved':True,'optimization':{'optimized_resume':'不应显示的旧美化正文'}}}
        app.run()
        self.assertFalse(any('不应显示的旧美化正文' in str(x.value) for x in app.markdown))
        self.assertFalse(any('美化' in b.label for b in app.button))
        self.assertFalse(app.exception)

    def test_confirmed_experiences_inform_checklist_without_resume_writes(self):
        app=self.app();value=envelope()
        for row in value['report']['requirements'][:2]:
            row.update(source='user_confirmed',status='partial',user_statement='使用 Python 实现过参数校验和接口错误处理。')
        value['report']['requirements'][2].update(source='user_confirmed',status='gap',user_statement='计划学习英语')
        app.session_state['career']=value
        with patch('web_client.request_api') as api:
            app.run()
        api.assert_not_called()
        self.assertEqual(len([t for t in app.text if t.value.startswith('本人确认的补充：')]),1)
        self.assertFalse(any(t.value=='本人确认的补充：计划学习英语' for t in app.text))
        self.assertFalse(any('另存' in b.label for b in app.button))
        self.assertFalse(app.exception)


class QuickReviewTests(unittest.TestCase):
    app = CareerUiTests.app
    def test_changed_sources_save_once_before_review_and_retry_reuses_ids(self):
        from web_client import ApiError
        app=self.app()
        app.text_area(key='resume_text').set_value('新的真实经历')
        app.text_area(key='jd_text').set_value('新的岗位要求').run()
        with patch('web_client.request_api', side_effect=[{'id':12}, {'id':15}, ApiError('暂时无法分析')]) as api:
            button(app,'分析岗位与能力差距').click().run()
        self.assertEqual([c.args[1] for c in api.call_args_list], ['/resumes','/job-descriptions','/career/review'])
        self.assertEqual(app.session_state['resume_id'],12)
        self.assertEqual(len(app.chat_input),0)
        with patch('web_client.request_api', return_value=envelope()) as api:
            button(app,'分析岗位与能力差距').click().run()
        self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.kwargs['data'], {'resume_id':12,'job_description_id':15})
        self.assertFalse(app.exception)


    def test_review_with_only_resume_and_jd(self):
        app=self.app()
        app.text_input(key='company').set_value('')
        app.text_input(key='job_title').set_value('').run()
        self.assertFalse(button(app,'分析岗位与能力差距').disabled)
        with patch('web_client.request_api',side_effect=[{'id':16},envelope()]) as api:
            button(app,'分析岗位与能力差距').click().run()
        self.assertEqual([c.args[1] for c in api.call_args_list], ['/job-descriptions','/career/review'])
        self.assertEqual(api.call_args_list[0].kwargs['data'], {'company':'','job_title':'','jd_text':'测试岗位要求'})
        self.assertFalse(app.exception)
        app.text_area(key='jd_text').set_value('   ').run()
        self.assertTrue(button(app,'分析岗位与能力差距').disabled)




class ChecklistProgressTests(unittest.TestCase):
    app=CareerUiTests.app

    def test_plan_failure_keeps_existing_checklist(self):
        from web_client import ApiError
        app=self.app()
        with patch('web_client.request_api',side_effect=ApiError('行动计划暂时无法生成')):
            button(app,'生成 / 更新行动计划').click().run()
        self.assertTrue(app.error)
        self.assertTrue(any(m.label=='目标事项' and m.value=='3' for m in app.metric))
        self.assertFalse(app.exception)

    def test_confirming_new_evidence_updates_checklist_immediately(self):
        app=self.app();value=envelope()
        value['report']['pending']=[{'requirement_id':'r1','status':'supported','statement':'我用 Python 开发过真实接口','reason':'自述'}]
        app.session_state['career']=value;app.run()
        updated=envelope();updated['report']['requirements'][0]['status']='supported'
        with patch('web_client.request_api',return_value=updated) as api:
            button(app,'准确，确认更新').click().run()
        self.assertEqual(api.call_count,1)
        self.assertTrue(any(m.label=='目标事项' and m.value=='2' for m in app.metric))
        self.assertFalse(app.exception)


class AdaptiveConfirmationTests(unittest.TestCase):
    app=CareerUiTests.app

    def pending_app(self):
        app=self.app(); value=envelope()
        value['report']['agent']={'enabled':True,'status':'waiting','note':'请先核实补充。'}
        value['report']['pending']=[{'requirement_id':'r1','status':'supported',
            'statement':'我用 Python 开发过接口鉴权','reason':'自述'}]
        app.session_state['career']=value
        return app.run()

    def test_confirm_commits_evidence_before_automatic_advance(self):
        app=self.pending_app()
        confirmed=envelope();confirmed['report_token']='confirmed-token'
        confirmed['report']['score']=43
        confirmed['report']['requirements'][0]['status']='supported'
        confirmed['report']['agent']={'enabled':True,'status':'waiting','note':'经历已确认。'}
        advanced=envelope();advanced['report_token']='advanced-token'
        advanced['report']['score']=43
        advanced['report']['requirements'][0]['status']='supported'
        advanced['report']['agent']={'enabled':True,'status':'waiting','note':'继续确认其他要求。'}
        advanced['report']['messages']=[{'role':'assistant','content':'你是否还做过知识检索？'}]

        def request(method,path,**kwargs):
            if path=='/career/confirm':
                return confirmed
            self.assertEqual(path,'/career/advance')
            self.assertEqual(app.session_state['career'],confirmed)
            self.assertEqual(kwargs['data'],{'report_token':'confirmed-token'})
            return advanced

        with patch('web_client.request_api',side_effect=request) as api:
            button(app,'准确，确认更新').click().run()
        self.assertEqual([c.args[1] for c in api.call_args_list],['/career/confirm','/career/advance'])
        self.assertEqual(app.session_state['career'],advanced)
        self.assertFalse(app.exception)
        with patch('web_client.request_api') as refresh:
            app.run()
        refresh.assert_not_called()

    def test_confirm_remains_saved_if_followup_advance_fails(self):
        from web_client import ApiError
        app=self.pending_app()
        confirmed=envelope();confirmed['report_token']='confirmed-token'
        confirmed['report']['score']=43
        confirmed['report']['agent']={'enabled':True,'status':'waiting','note':'经历已确认。'}
        with patch('web_client.request_api',side_effect=[confirmed,ApiError('安排下一步暂时失败',502)]) as api:
            button(app,'准确，确认更新').click().run()
        self.assertEqual([c.args[1] for c in api.call_args_list],['/career/confirm','/career/advance'])
        self.assertEqual(app.session_state['career'],confirmed)
        self.assertEqual(app.session_state['career']['report']['score'],43)
        self.assertFalse(app.exception)

    def test_confirm_does_not_advance_with_unreviewed_proposals_or_disabled_agent(self):
        for remaining,enabled in ((True,True),(False,False)):
            with self.subTest(remaining=remaining,enabled=enabled):
                app=self.pending_app();confirmed=envelope()
                confirmed['report']['agent']={'enabled':enabled,'status':'waiting','note':''}
                if remaining:
                    confirmed['report']['pending']=[{'requirement_id':'r2','status':'partial',
                        'statement':'我只做过检索原型','reason':'尚待核实'}]
                with patch('web_client.request_api',return_value=confirmed) as api:
                    button(app,'准确，确认更新').click().run()
                self.assertEqual([c.args[1] for c in api.call_args_list],['/career/confirm'])
                self.assertEqual(app.session_state['career'],confirmed)
                self.assertFalse(app.exception)

    def test_manual_plan_can_skip_clarification_but_cannot_auto_confirm(self):
        app=self.app()
        waiting=envelope()
        waiting['report']['agent']={'enabled':True,'status':'waiting','next_action':'clarify'}
        app.session_state['career']=waiting
        app.run()
        advanced=envelope()
        advanced['report']['agent']={'enabled':True,'status':'complete','note':'已按当前证据整理行动。'}
        with patch('web_client.request_api',return_value=advanced) as api:
            button(app,'生成 / 更新行动计划').click().run()
        api.assert_called_once_with('POST','/career/advance',token='test-token',
            data={'report_token':'opaque-test-token','skip_clarification':True})
        self.assertFalse(app.exception)

    def test_pending_confirmation_disables_plan_control(self):
        app=self.pending_app()
        self.assertTrue(button(app,'生成 / 更新行动计划').disabled)

    def test_hard_conditions_only_can_skip_clarification_without_learning_plan(self):
        app=self.app()
        waiting=envelope()
        waiting['report']['requirements']=[waiting['report']['requirements'][-1]]
        waiting['report']['agent']={'enabled':True,'status':'waiting','next_action':'clarify'}
        app.session_state['career']=waiting
        app.run()
        self.assertFalse(button(app,'跳过提问，查看清单').disabled)
        completed=envelope()
        completed['report']['requirements']=waiting['report']['requirements']
        completed['report']['agent']={'enabled':True,'status':'complete','next_action':'done'}
        with patch('web_client.request_api',return_value=completed) as api:
            button(app,'跳过提问，查看清单').click().run()
        api.assert_called_once_with('POST','/career/advance',token='test-token',
            data={'report_token':'opaque-test-token','skip_clarification':True})
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['career']['report']['tasks'],[])
