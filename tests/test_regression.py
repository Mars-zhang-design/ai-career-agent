"""Offline behavioral regression tests. No real keys, network calls or DB writes."""
import os
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['JWT_SECRET_KEY'] = 'test-only-secret-that-is-at-least-32-bytes-long'
os.environ['DEEPSEEK_API_KEY'] = 'test-only-unused-key'

import time
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, timezone
import jwt
from fastapi.testclient import TestClient
from agent_graph import build_graph
from agent_tools import BusinessTools, ToolContext
from repositories import RecordNotFound
import repositories
import resume_optimizer
import auth_service
import main

ANALYSIS = dict(match_score=75, matched_skills=['Python'], missing_skills=['Redis'],
                jd_keywords=['Python'], warnings=[], evidence=['使用 Python'])
OPTIMIZATION = {**{k:v for k,v in ANALYSIS.items() if k != 'evidence'},
                'optimized_resume': '使用 Python 开发服务',
                'rewrite_suggestions': [{'original':'使用 Python', 'optimized':'使用 Python 开发服务'}]}


def initial(**overrides):
    return dict(task_id='offline-test', resume_id=11, job_description_id=22,
                instruction='优化', mode='optimize', match_threshold=60, use_knowledge=False,
                status='running', step_count=0, repair_count=0, errors=[], warnings=[], trace=[],
                knowledge=[], knowledge_attempted=False, deadline=time.monotonic()+120, **overrides)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch('repositories.get_resume', return_value={'id':11, 'resume_text':'使用 Python'}),
            patch('repositories.get_job_description', return_value={'id':22, 'jd_text':'需要 Python 和 Redis'}),
            patch('repositories.save_optimization_result', return_value=33),
            patch('resume_optimizer.analyze_match', return_value=ANALYSIS.copy()),
            patch('resume_optimizer.optimize_resume', return_value=OPTIMIZATION.copy()),
        ]
        self.resume, self.jd, self.save, self.analyze, self.optimize = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.tools = BusinessTools(ToolContext(7))

    def run_graph(self, state=None, **kwargs):
        return build_graph(self.tools, **kwargs).invoke(state or initial(), {'recursion_limit':32})

    def test_full_run_reads_owner_records_and_saves_once(self):
        final = self.run_graph()
        self.assertEqual(final['status'], 'success')
        self.assertEqual(final['record_id'], 33)
        self.resume.assert_called_once_with(7,11)
        self.jd.assert_called_once_with(7,22)
        self.save.assert_called_once()
        self.assertEqual([s['tool'] for s in final['trace']],
                         ['get_resume','get_job_description','analyze_match','optimize_resume','save_optimization_result'])

    def test_analysis_only_never_optimizes_or_saves(self):
        state=initial(); state['mode']='analyze'
        self.assertEqual(self.run_graph(state)['status'], 'success')
        self.optimize.assert_not_called(); self.save.assert_not_called()

    def test_conditional_below_threshold(self):
        state=initial(); state.update(mode='conditional', match_threshold=80)
        self.assertEqual(self.run_graph(state)['status'], 'success')
        self.optimize.assert_not_called(); self.save.assert_not_called()

    def test_conditional_equal_threshold_optimizes(self):
        state=initial(); state.update(mode='conditional', match_threshold=75)
        self.assertEqual(self.run_graph(state)['status'], 'success')
        self.save.assert_called_once()

    def test_missing_or_foreign_record_stops_before_model(self):
        self.resume.side_effect=RecordNotFound()
        result=self.run_graph()
        self.assertEqual(result['errors'][0]['code'],'not_found')
        self.jd.assert_not_called(); self.analyze.assert_not_called(); self.save.assert_not_called()

    def test_rag_failure_is_visible_and_nonfatal(self):
        state=initial(); state['use_knowledge']=True
        decide=Mock(return_value={'action':'retrieve_job_knowledge','query':'Redis 要求'})
        with patch('rag_chroma.retrieve', side_effect=RuntimeError('private source')):
            result=self.run_graph(state, decide=decide)
        self.assertEqual(result['status'],'success')
        self.assertIn('知识检索不可用',result['warnings'][0])
        self.assertNotIn('private source',str(result))
        self.save.assert_called_once()

    def test_retrieval_is_passed_to_analysis_and_optimization(self):
        state=initial(); state['use_knowledge']=True
        knowledge=[{'content':'Redis 是缓存系统','metadata':{'source':'knowledge.txt','chunk_id':1},'distance':0.1}]
        with patch('rag_chroma.retrieve', return_value=knowledge):
            result=self.run_graph(state,decide=lambda *_:{'action':'retrieve_job_knowledge','query':'Redis'})
        self.assertEqual(result['status'],'success')
        self.assertEqual(self.analyze.call_args.args[2],knowledge)
        self.assertEqual(self.optimize.call_args.args[3],knowledge)

    def test_invalid_planner_action_cannot_skip_to_save(self):
        state=initial(); state['use_knowledge']=True
        result=self.run_graph(state,decide=lambda *_:{'action':'save_optimization_result','user_id':99})
        self.assertEqual(result['status'],'success')
        self.assertIn('决策模型不可用',result['warnings'][0])
        self.assertEqual(result['trace'][-1]['tool'],'save_optimization_result')

    def test_save_failure_never_claims_success_or_retries(self):
        self.save.side_effect=RuntimeError('password must stay private')
        result=self.run_graph()
        self.assertEqual(result['status'],'error')
        self.assertEqual(result['errors'][0]['code'],'save_failed')
        self.assertNotIn('record_id',result)
        self.assertNotIn('password',str(result))
        self.save.assert_called_once()

    def test_unsafe_rewrite_repaired_once_then_rejected(self):
        self.optimize.return_value={**OPTIMIZATION,'optimized_resume':'精通 Redis'}
        result=self.run_graph()
        self.assertEqual(result['status'],'error')
        self.assertEqual(self.optimize.call_count,2)
        self.save.assert_not_called()

    def test_bounded_repair_can_succeed(self):
        self.optimize.side_effect=[{**OPTIMIZATION,'optimized_resume':'Redis'},OPTIMIZATION]
        result=self.run_graph()
        self.assertEqual(result['status'],'success')
        self.assertEqual(self.optimize.call_count,2)
        self.save.assert_called_once()

    def test_step_limit_stops_before_save(self):
        result=self.run_graph(max_steps=3)
        self.assertEqual(result['errors'][0]['code'],'step_limit')
        self.save.assert_not_called()

    def test_deadline_stops_before_io(self):
        state=initial(); state['deadline']=time.monotonic()-1
        result=self.run_graph(state)
        self.assertEqual(result['errors'][0]['code'],'timeout')
        self.resume.assert_not_called()

    def test_text_mode_never_saves(self):
        self.tools=BusinessTools(ToolContext(None,persist=False))
        state=initial();state.update(resume='使用 Python',job_description='需要 Python')
        self.assertEqual(self.run_graph(state)['status'],'success')
        self.resume.assert_not_called();self.save.assert_not_called()

    def test_copy_is_retried_and_never_saved(self):
        self.optimize.return_value={**OPTIMIZATION, 'optimized_resume':'使用 Python',
            'rewrite_suggestions':[{'original':'使用 Python','optimized':'使用 Python'}]}
        result=self.run_graph()
        self.assertEqual(result['status'],'error')
        self.assertEqual(result['errors'][0]['code'],'no_effective_optimization')
        self.assertEqual(self.optimize.call_count,2)
        self.assertTrue(self.optimize.call_args.args[4])
        self.save.assert_not_called()

    def test_copy_repair_applies_changed_result_and_saves_once(self):
        self.optimize.side_effect=[{**OPTIMIZATION,'optimized_resume':'使用 Python'},OPTIMIZATION]
        result=self.run_graph()
        self.assertEqual(result['status'],'success')
        self.assertEqual(self.optimize.call_count,2)
        self.save.assert_called_once()

    def test_save_boundary_rejects_copied_result(self):
        state=initial();state.update(resume='使用 Python', optimization_result={
            **OPTIMIZATION,'optimized_resume':'使用 Python'})
        with self.assertRaises(resume_optimizer.NoEffectiveOptimization):
            self.tools.save_optimization_result(state,{})
        self.save.assert_not_called()


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.connection=Mock();self.cursor=Mock()
        self.connection.cursor.return_value=self.cursor
        self.patcher=patch('repositories.get_db_connection',return_value=self.connection)
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def test_queries_bind_owner_and_id(self):
        self.cursor.fetchone.return_value=None
        with self.assertRaises(RecordNotFound): repositories.get_resume(7,11)
        sql, params=self.cursor.execute.call_args.args
        self.assertIn('user_id=%s',sql);self.assertEqual(params,(11,7))
        self.cursor.close.assert_called_once();self.connection.close.assert_called_once()

    def test_save_rechecks_both_owners(self):
        self.cursor.fetchone.side_effect=[{'id':11},None]
        with self.assertRaises(RecordNotFound): repositories.save_optimization_result(7,11,22,OPTIMIZATION)
        self.connection.commit.assert_not_called()
        self.assertEqual(self.cursor.execute.call_count,2)
        self.connection.rollback.assert_called_once()

    def test_commit_failure_rolls_back_and_is_not_retried(self):
        self.cursor.fetchone.return_value={'id':11}
        self.connection.commit.side_effect=RuntimeError()
        with self.assertRaises(RuntimeError): repositories.save_optimization_result(7,11,22,OPTIMIZATION)
        self.connection.commit.assert_called_once();self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(main.app,raise_server_exceptions=False)
        self.addCleanup(main.app.dependency_overrides.clear)

    def login(self):
        main.app.dependency_overrides[main.get_current_user]=lambda:{'id':7,'name':'Test'}

    def test_new_endpoint_requires_bearer_auth(self):
        response=self.client.post('/resume/agent-by-id',json={'resume_id':11,'job_description_id':22})
        self.assertIn(response.status_code,(401,403))

    def test_new_request_validates_ids(self):
        self.login()
        response=self.client.post('/resume/agent-by-id',json={'resume_id':0,'job_description_id':22})
        self.assertEqual(response.status_code,422)

    def test_legacy_error_response_accepts_none(self):
        response=self.client.post('/resume/agent',json={'resume':'','job_description':'test','instruction':''})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'error')
        self.assertIsNone(response.json()['result'])

    def test_legacy_optimize_by_id_contract(self):
        self.login()
        with patch('main.get_resume',return_value={'id':11,'resume_text':'使用 Python'}), \
             patch('main.get_job_description',return_value={'id':22,'jd_text':'Python'}), \
             patch('main.analyze_resume_jd',return_value=OPTIMIZATION), \
             patch('main.save_optimization_result',return_value=33) as save:
            response=self.client.post('/resume/optimize-by-id',json={'resume_id':11,'job_description_id':22})
        self.assertEqual(response.status_code,200)
        from schemas import ResumeOptimizeResponse
        self.assertEqual(response.json(),ResumeOptimizeResponse.model_validate(OPTIMIZATION).model_dump())
        self.assertEqual(save.call_args.args[:3],(7,11,22))

    def test_new_api_maps_foreign_record_to_404(self):
        self.login()
        with patch('resume_agent.save_summary'), patch('repositories.get_resume',side_effect=RecordNotFound()):
            response=self.client.post('/resume/agent-by-id',json={'resume_id':11,'job_description_id':22})
        self.assertEqual(response.status_code,404)
        self.assertFalse(response.json()['saved'])

    def test_task_summary_scoped_to_authenticated_user(self):
        self.login()
        with patch('main.get_summary',return_value=None) as summary:
            response=self.client.get('/tasks/00000000-0000-0000-0000-000000000001')
        self.assertEqual(response.status_code,404)
        self.assertEqual(summary.call_args.args[0],7)

    def test_demo_task_cannot_write_another_user(self):
        self.login()
        with patch('main.save_summary') as save:
            response=self.client.post('/task/start',json={'user_id':'999'})
        self.assertEqual(response.status_code,403);save.assert_not_called()

    def test_create_resume_uses_authenticated_identity(self):
        self.login();connection=Mock();cursor=Mock(lastrowid=11);connection.cursor.return_value=cursor
        with patch('main.get_db_connection',return_value=connection):
            response=self.client.post('/resumes',json={'resume_text':'使用 Python'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(cursor.execute.call_args.args[1],(7,'使用 Python'))
        connection.commit.assert_called_once()


class AuthTests(unittest.TestCase):
    def test_jwt_round_trip(self):
        token=auth_service.create_access_token(7,'test@example.invalid')
        self.assertEqual(auth_service.decode_access_token(token)['user_id'],7)

    def test_expired_and_invalid_tokens(self):
        token=jwt.encode({'user_id':7,'exp':datetime.now(timezone.utc)-timedelta(seconds=1)},
                         auth_service.JWT_SECRET_KEY,algorithm='HS256')
        self.assertIn('error',auth_service.decode_access_token(token))
        self.assertIn('error',auth_service.decode_access_token('not.a.token'))

    def test_registration_hashes_password(self):
        connection=Mock();cursor=Mock(lastrowid=7);cursor.fetchone.return_value=None
        connection.cursor.return_value=cursor
        with patch('auth_service.get_db_connection',return_value=connection):
            result=auth_service.register_user('Test','TEST@example.invalid','password123')
        self.assertEqual(result['id'],7)
        values=cursor.execute.call_args.args[1]
        self.assertEqual(values[1],'test@example.invalid')
        self.assertNotEqual(values[2],'password123')
        self.assertTrue(auth_service.bcrypt.checkpw(b'password123',values[2].encode()))

    def test_login_checks_hash_and_returns_token(self):
        connection=Mock();cursor=Mock();connection.cursor.return_value=cursor
        cursor.fetchone.return_value={'id':7,'name':'Test','email':'test@example.invalid',
            'password_hash':auth_service.bcrypt.hashpw(b'password123',auth_service.bcrypt.gensalt()).decode()}
        with patch('auth_service.get_db_connection',return_value=connection):
            result=auth_service.login_user('test@example.invalid','password123')
            wrong=auth_service.login_user('test@example.invalid','incorrect')
        self.assertEqual(auth_service.decode_access_token(result['access_token'])['user_id'],7)
        self.assertIn('error',wrong)

    def test_long_password_returns_validation_error(self):
        with patch('auth_service.get_db_connection') as db:
            self.assertIn('error',auth_service.register_user('Test','x@example.invalid','密'*25))
        db.assert_not_called()


class ReliabilityTests(unittest.TestCase):
    def test_model_parser_retry_has_one_owner(self):
        import json
        import llm_service
        from schemas import MatchAnalysis
        from langchain_core.runnables import RunnableLambda
        responses=iter(['not json',json.dumps(ANALYSIS)])
        model=RunnableLambda(lambda _: next(responses))
        with patch('llm_service.ChatOpenAI',return_value=model) as factory, patch('llm_service.time.sleep'):
            result=llm_service.structured_call(MatchAnalysis,'test',{'resume':'test'})
        self.assertEqual(result.match_score,75)
        self.assertEqual(factory.call_count,2)
        self.assertEqual(factory.call_args.kwargs['max_retries'],0)
        self.assertEqual(factory.call_args.kwargs['timeout'],30)

    def test_permanent_model_error_is_not_retried(self):
        import llm_service
        from schemas import MatchAnalysis
        from langchain_core.runnables import RunnableLambda
        def fail(_): raise ValueError('configuration error')
        with patch('llm_service.ChatOpenAI',return_value=RunnableLambda(fail)) as factory:
            with self.assertRaises(ValueError):
                llm_service.structured_call(MatchAnalysis,'test',{})
        self.assertEqual(factory.call_count,1)

    def test_model_deadline_prevents_call(self):
        import llm_service
        from schemas import MatchAnalysis
        with patch('llm_service.ChatOpenAI') as factory:
            with self.assertRaises(TimeoutError):
                llm_service.structured_call(MatchAnalysis,'test',{},time.monotonic()-1)
        factory.assert_not_called()

    def test_redis_failure_does_not_fail_business(self):
        import redis
        import task_store
        with patch('task_store.client',side_effect=redis.ConnectionError()):
            task_store.save_summary(7,initial())

    def test_rag_caps_top_k_to_available_documents(self):
        import rag_chroma
        model=Mock();model.encode.return_value.tolist.return_value=[[1.0]]
        index=Mock();index.count.return_value=1
        index.query.return_value={'documents':[['Python']],
            'metadatas':[[{'source':'knowledge.txt','chunk_id':1}]],'distances':[[0.1]]}
        with patch('rag_chroma.initialize_rag'),patch('rag_chroma.embedding_model',model),patch('rag_chroma.collection',index):
            result=rag_chroma.retrieve('Python',top_k=3)
        self.assertEqual(index.query.call_args.kwargs['n_results'],1)
        self.assertEqual(result[0]['metadata']['source'],'knowledge.txt')

    def test_graph_success_api_returns_real_record_id(self):
        main.app.dependency_overrides[main.get_current_user]=lambda:{'id':7}
        self.addCleanup(main.app.dependency_overrides.clear)
        with patch('resume_agent.save_summary'), \
             patch('repositories.get_resume',return_value={'id':11,'resume_text':'使用 Python'}), \
             patch('repositories.get_job_description',return_value={'id':22,'jd_text':'Python'}), \
             patch('repositories.save_optimization_result',return_value=33), \
             patch('resume_optimizer.analyze_match',return_value=ANALYSIS), \
             patch('resume_optimizer.optimize_resume',return_value=OPTIMIZATION):
            response=TestClient(main.app).post('/resume/agent-by-id',json={
                'resume_id':11,'job_description_id':22,'use_knowledge':False})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['record_id'],33)
        self.assertTrue(response.json()['saved'])


class RewriteValidationTests(unittest.TestCase):
    def test_cosmetic_changes_are_rejected(self):
        for final in ('使用 Python', ' 使用  Python\n', '使用 PYTHON。', '使用 Ｐｙｔｈｏｎ'):
            with self.subTest(final=final):
                result={**OPTIMIZATION,'optimized_resume':final,
                    'rewrite_suggestions':[{'original':'使用 Python','optimized':final}]}
                self.assertTrue(resume_optimizer.validate_resume_result('使用 Python', result))

    def test_unchanged_suggestion_is_rejected_even_when_document_changes(self):
        result={**OPTIMIZATION,'rewrite_suggestions':[
            {'original':'使用 Python','optimized':'使用 Python'}]}
        self.assertTrue(resume_optimizer.validate_resume_result('使用 Python', result))

    def test_unapplied_suggestion_is_rejected(self):
        result={**OPTIMIZATION,'optimized_resume':'Python 使用经验'}
        self.assertTrue(resume_optimizer.validate_resume_result('使用 Python', result))

    def test_empty_suggestions_do_not_prove_effective_rewrite(self):
        result={**OPTIMIZATION,'rewrite_suggestions':[]}
        self.assertTrue(resume_optimizer.validate_resume_result('使用 Python', result))

    def test_valid_fact_preserving_rewrite(self):
        original='我使用 Python 编写后端逻辑，并采用 MySQL 完成数据存储。'
        final='使用 Python 开发后端逻辑，使用 MySQL 存储数据。'
        result={**OPTIMIZATION,'optimized_resume':final,
                'rewrite_suggestions':[{'original':original,'optimized':final}]}
        self.assertEqual(resume_optimizer.validate_resume_result(original,result),[])

    def test_legacy_path_rejects_copy_after_two_attempts(self):
        result={**OPTIMIZATION,'optimized_resume':'使用 Python'}
        with patch('resume_optimizer.analyze_match',return_value=ANALYSIS), \
             patch('resume_optimizer.optimize_resume',return_value=result) as optimize:
            with self.assertRaises(resume_optimizer.NoEffectiveOptimization):
                resume_optimizer.analyze_resume_jd('使用 Python','Python')
        self.assertEqual(optimize.call_count,2)

    def test_legacy_api_returns_explicit_validation_error(self):
        with patch('main.analyze_resume_jd',side_effect=resume_optimizer.NoEffectiveOptimization()):
            response=TestClient(main.app).post('/resume/optimize',json={
                'resume':'使用 Python','job_description':'Python'})
        self.assertEqual(response.status_code,502)
        self.assertEqual(response.json()['detail']['code'],'no_effective_optimization')


if __name__ == '__main__':
    unittest.main()
