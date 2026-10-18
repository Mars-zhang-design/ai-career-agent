"""History authorization, persistence boundaries and return-to-work flows."""
import unittest
from unittest.mock import Mock, patch
from contextlib import contextmanager
from fastapi.testclient import TestClient
from test_career import report, RESUME, JD
from test_web import button
import main
import career_service as service
import history_repository as history
from history_api import load_progress
from streamlit.testing.v1 import AppTest
from pathlib import Path


class HistoryRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.connection=Mock();self.cursor=Mock(lastrowid=10)
        self.connection.cursor.return_value=self.cursor
        p=patch('repositories.get_db_connection',return_value=self.connection)
        p.start();self.addCleanup(p.stop)

    def test_detail_is_bound_to_owner_for_every_kind(self):
        self.cursor.fetchone.return_value=None
        for kind in history.KINDS:
            with self.assertRaises(history.RecordNotFound): history.get_record(7,kind,9)
            sql,args=self.cursor.execute.call_args.args
            self.assertIn('id=%s AND user_id=%s',sql)
            self.assertEqual(args,(9,7))

    def test_listing_is_owner_scoped_and_paginated(self):
        self.cursor.fetchall.return_value=[{'id':i} for i in range(25,4,-1)]
        for kind in history.KINDS:
            result=history.list_records(7,kind,before=30)
            sql,args=self.cursor.execute.call_args.args
            self.assertIn('user_id=%s',sql)
            self.assertEqual(args[0],7)
            self.assertEqual(args[-2:],(30,21))
            self.assertEqual(len(result['items']),20)
            self.assertEqual(result['next_before'],6)

    def test_snapshot_persists_report_without_access_tokens(self):
        r=report()
        identity=history.save_snapshot(7,r,'review')
        sql,args=self.cursor.execute.call_args.args
        self.assertEqual(identity,10)
        self.assertEqual(args[0],7)
        self.assertEqual(args[1],r.workspace_id)
        self.assertIn('ON DUPLICATE KEY',sql)
        self.assertNotIn('report_token',args[-1])
        self.connection.commit.assert_called_once()

    def test_unknown_kind_cannot_select_arbitrary_table(self):
        with self.assertRaises(ValueError): history.get_record(7,'users',1)
        self.cursor.execute.assert_not_called()


class HistoryApiTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(main.app)
        self.addCleanup(main.app.dependency_overrides.clear)

    def login(self):
        main.app.dependency_overrides[main.get_current_user]=lambda:{'id':7}

    def test_all_history_routes_require_login(self):
        for url in ('/history/resumes','/history/jobs/1','/history/optimizations/1','/history/sessions/1/resume'):
            self.assertIn(self.client.get(url).status_code,(401,403))

    def test_history_detail_uses_server_identity_and_hides_missing_rows(self):
        self.login()
        with patch('history_repository.get_record',side_effect=history.RecordNotFound()) as get:
            response=self.client.get('/history/optimizations/123?user_id=999')
        self.assertEqual(response.status_code,404)
        self.assertEqual(get.call_args.args,(7,'optimizations',123))

    def test_restore_reissues_signed_token_without_using_expired_token(self):
        r=report()
        records=[{'id':5,'report_json':r.model_dump_json()},
                 {'id':2,'resume_text':RESUME}, {'id':5,'jd_text':JD,'job_title':'测试岗位','company':'合成公司'}]
        with patch('history_repository.get_record',side_effect=records):
            result=load_progress(7,5)
        self.assertTrue(result['career']['history_saved'])
        with patch('career_service.source_text',return_value=(RESUME,JD)):
            restored,_,_=service.restore(result['career']['report_token'],7)
            self.assertEqual(restored.workspace_id,r.workspace_id)
            with self.assertRaises(service.ReportError): service.restore(result['career']['report_token'],8)

    def test_source_changes_block_restoring_stale_analysis(self):
        records=[{'report_json':report().model_dump_json()}, {'resume_text':'changed'}, {'jd_text':JD}]
        with patch('history_repository.get_record',side_effect=records):
            with self.assertRaises(service.ReportError): load_progress(7,5)

    def test_review_auto_saves_and_reports_persistence_failure_honestly(self):
        self.login()
        for fail in (False,True):
            result=service.envelope(report(),7)
            with patch('career_service.review',return_value=result) as action, \
                 patch('career_api.save_snapshot',side_effect=RuntimeError('private') if fail else None,return_value=9):
                action.__name__='review'
                response=self.client.post('/career/review',json={'resume_id':2,'job_description_id':5})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['history_saved'],not fail)
            if fail:
                self.assertTrue(response.json()['persistence_warning'])
                self.assertNotIn('private',response.text)

    def test_manual_save_checks_signed_report_and_account(self):
        self.login()
        with patch('history_repository.save_snapshot') as save:
            response=self.client.post('/history/save-progress',json={'report_token':service.envelope(report(),8).report_token})
        self.assertEqual(response.status_code,409)
        save.assert_not_called()

    def test_manual_save_returns_fresh_report_token_for_legacy_sessions(self):
        self.login()
        r=report()
        token=service.envelope(r,7).report_token
        with patch('career_service.source_text',return_value=(RESUME,JD)), \
             patch('history_repository.save_snapshot',return_value=10):
            response=self.client.post('/history/save-progress',json={'report_token':token})
        self.assertEqual(response.status_code,200)
        value=response.json()
        self.assertTrue(value['career']['history_saved'])
        self.assertEqual(value['career']['report']['workspace_id'],r.workspace_id)
        self.assertTrue(value['career']['report_token'])


class HistoryUiTests(unittest.TestCase):
    def app(self):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'web_app.py'),default_timeout=15)
        app.session_state['token']='test-token'
        app.session_state['user_name']='测试用户'
        return app.run()

    def open_history(self,app,kind,rows):
        app.session_state['history_kind']=kind
        with patch('web_client.request_api',return_value={'items':rows,'next_before':None}):
            app.radio(key='workspace_page').set_value('我的历史').run()
        return app

    def test_optimization_is_accessible_after_new_login_session(self):
        app=self.open_history(self.app(),'optimizations',[{'id':9,'resume_id':2,'created_at':'2026-10-18'}])
        with patch('web_client.request_api',return_value={'id':9,'optimized_resume':'之前保存的简历正文'}):
            button(app,'打开记录').click().run()
        self.assertTrue(any(t.value=='之前保存的简历正文' for t in app.text))
        self.assertFalse(app.exception)

    def test_resume_loading_returns_to_work_without_saving_duplicate(self):
        app=self.open_history(self.app(),'resumes',[{'id':2,'title':'已有简历','created_at':'2026-10-18'}])
        with patch('web_client.request_api',return_value={'id':2,'resume_text':RESUME}):
            button(app,'打开记录').click().run()
        with patch('web_client.request_api') as api:
            button(app,'使用这份简历').click().run()
        api.assert_not_called()
        self.assertEqual(app.session_state['resume_id'],2)
        self.assertEqual(app.text_area(key='resume_text').value,RESUME)
        self.assertTrue(button(app,'保存简历').disabled)
        self.assertFalse(app.exception)

    def test_restore_progress_repopulates_context_and_preserves_tasks(self):
        r=report();value=service.envelope(r,7).model_dump();value['history_saved']=True
        app=self.open_history(self.app(),'sessions',[{'id':9,'resume_id':2,'job_description_id':5,'action':'chat','created_at':'today'}])
        with patch('web_client.request_api',return_value={'id':9,'report':r.model_dump()}):
            button(app,'打开记录').click().run()
        restored={'career':value,'resume':{'id':2,'resume_text':RESUME},
                  'job':{'id':5,'company':'合成公司','job_title':'测试岗位','jd_text':JD}}
        with patch('web_client.request_api',return_value=restored) as api:
            button(app,'恢复进度，继续工作').click().run()
        self.assertEqual(api.call_count,1)
        self.assertEqual(app.session_state['career']['report']['workspace_id'],r.workspace_id)
        self.assertEqual(app.session_state['workspace_page'],'工作台')
        self.assertEqual(len(app.chat_input),1)
        self.assertFalse(any(b.label=='保存当前进度' for b in app.button))
        self.assertFalse(app.exception)

    def test_logout_clears_history_cache(self):
        app=self.open_history(self.app(),'jobs',[])
        button(app,'退出登录').click().run()
        self.assertNotIn('history_list_jobs_0',app.session_state)
        self.assertNotIn('token',app.session_state)
