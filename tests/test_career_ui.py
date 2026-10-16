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
        self.assertTrue(button(app,'美化当前简历'))
        self.assertTrue(button(app,'生成目标简历预览'))
        self.assertTrue(button(app,'开始处理'))

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

    def test_target_export_is_visibly_marked(self):
        app=self.app()
        with patch('web_client.request_api',return_value={'text':'目标简历\n【待完成】RAG实践','pending_count':1,'is_target':True}):
            button(app,'生成目标简历预览').click().run()
        self.assertTrue(any('请勿直接' in w.value for w in app.warning))
        self.assertFalse(app.exception)

    def test_changed_input_blocks_old_conversation(self):
        app=self.app()
        app.text_area(key='resume_text').set_value('已修改的新简历').run()
        self.assertEqual(len(app.chat_input),0)
        self.assertTrue(button(app,'分析岗位与能力差距').disabled)
        self.assertFalse(app.exception)

    def test_review_button_uses_saved_ids(self):
        app=self.app()
        with patch('web_client.request_api',return_value=envelope()) as api:
            button(app,'分析岗位与能力差距').click().run()
        self.assertEqual(api.call_args.args[1],'/career/review')
        self.assertEqual(api.call_args.kwargs['data'],{'resume_id':2,'job_description_id':5})
        self.assertFalse(app.exception)
