"""Synthetic career cases: no private resumes, network, database writes or paid calls."""
import time
import unittest
from unittest.mock import patch
from test_career import report, RESUME, JD
from career_models import LearningDraft, LearningTask, LearningReference
import career_service as service
from plan_knowledge import collect_references


HIT = {'content': '使用 Python 编写接口并测试错误输入。', 'metadata': {
    'title': 'Python 官方教程', 'source_url': 'https://docs.python.org/3/tutorial/',
    'source': 'learning_resources/python.md', 'updated_at': '2026-10-18'}, 'distance': 0.2}


def generate(schema, rules, payload, *args, **kwargs):
    return LearningDraft(tasks=[LearningTask(
        requirement_id=row['id'], objective='练习接口开发', actions=['实现输入校验'],
        deliverable='代码与测试报告', acceptance=['无效输入得到明确提示'],
        source_ids=[ref['id'] for ref in payload['knowledge_by_requirement'][row['id']]][:1])
        for row in payload['requirements']])


class PlanKnowledgeTests(unittest.TestCase):
    def setUp(self):
        source = patch('career_service.source_text', return_value=(RESUME, JD))
        source.start(); self.addCleanup(source.stop)
        archive = patch('career_api.save_snapshot', return_value=1)
        archive.start(); self.addCleanup(archive.stop)
        self.token = service.envelope(report(), 1).report_token

    def test_references_flow_to_model_and_signed_response_without_changing_facts(self):
        before = report()
        with patch('rag_chroma.retrieve', return_value=[HIT]) as retrieve, \
             patch('career_service.structured_call', side_effect=generate) as llm:
            result = service.make_plan(1, self.token)
        self.assertEqual(retrieve.call_count, 2)
        self.assertTrue(all('英语' not in call.args[0] for call in retrieve.call_args_list))
        self.assertEqual(result.report.score, before.score)
        self.assertEqual(result.report.requirements, before.requirements)
        self.assertEqual(result.report.tasks[0].reference_status, 'cited')
        self.assertEqual(result.report.tasks[0].references[0].source_url, HIT['metadata']['source_url'])
        self.assertIn(HIT['content'], str(llm.call_args.args[2]))
        restored, _, _ = service.restore(result.report_token, 1)
        self.assertEqual(restored.tasks, result.report.tasks)
        self.assertEqual(service.confirmed_resume(restored, RESUME), RESUME)

    def test_retrieval_failure_still_produces_labelled_general_advice(self):
        with patch('rag_chroma.retrieve', side_effect=RuntimeError('private credential')), \
             patch('career_service.structured_call', side_effect=generate):
            result = service.make_plan(1, self.token)
        self.assertTrue(all(t.reference_status == 'unavailable' and not t.references for t in result.report.tasks))
        self.assertNotIn('private credential', result.model_dump_json())

    def test_no_hits_and_uncited_hits_are_distinct(self):
        with patch('rag_chroma.retrieve', return_value=[]), \
             patch('career_service.structured_call', side_effect=generate):
            empty = service.make_plan(1, self.token)
        self.assertEqual(empty.report.tasks[0].reference_status, 'empty')
        def uncited(*args, **kwargs):
            draft = generate(*args, **kwargs)
            for task in draft.tasks: task.source_ids = []
            return draft
        with patch('rag_chroma.retrieve', return_value=[HIT]), \
             patch('career_service.structured_call', side_effect=uncited):
            result = service.make_plan(1, self.token)
        self.assertEqual(result.report.tasks[0].reference_status, 'uncited')
        self.assertEqual(result.report.tasks[0].references, [])

    def test_fabricated_citation_is_rejected_after_bounded_retry(self):
        def bad(*args, **kwargs):
            draft = generate(*args, **kwargs)
            draft.tasks[0].source_ids = ['invented']
            return draft
        with patch('rag_chroma.retrieve', return_value=[HIT]), \
             patch('career_service.structured_call', side_effect=bad) as llm:
            with self.assertRaises(service.ReportError): service.make_plan(1, self.token)
        self.assertEqual(llm.call_count, 2)

    def test_model_cannot_supply_reference_objects_or_links(self):
        def bad(*args, **kwargs):
            draft = generate(*args, **kwargs)
            draft.tasks[0].actions = ['访问 https://invented.invalid/course']
            return draft
        with patch('rag_chroma.retrieve', return_value=[HIT]), \
             patch('career_service.structured_call', side_effect=bad):
            with self.assertRaises(service.ReportError): service.make_plan(1, self.token)
        def objects(*args, **kwargs):
            draft = generate(*args, **kwargs)
            draft.tasks[0] = LearningTask(**draft.tasks[0].model_dump(exclude={'references', 'reference_status'}), references=[LearningReference(
                id='fake', title='fake', source_url='https://fake.invalid', excerpt='fake', source='fake')])
            return draft
        with patch('rag_chroma.retrieve', return_value=[HIT]), \
             patch('career_service.structured_call', side_effect=objects):
            result = service.make_plan(1, self.token)
        self.assertNotIn('fake.invalid', result.model_dump_json())

    def test_cross_requirement_citation_is_not_accepted(self):
        other = {**HIT, 'content': 'RAG 检索实践'}
        def wrong(*args, **kwargs):
            draft = generate(*args, **kwargs)
            draft.tasks[0].source_ids = draft.tasks[1].source_ids
            return draft
        with patch('rag_chroma.retrieve', side_effect=[[HIT], [other]]), \
             patch('career_service.structured_call', side_effect=wrong):
            with self.assertRaises(service.ReportError): service.make_plan(1, self.token)

    def test_supported_and_example_rows_do_not_trigger_retrieval(self):
        r = report(); r.requirements[0].status = 'supported'; r.requirements[1].importance = 'example'
        with patch('rag_chroma.retrieve') as retrieve, patch('career_service.structured_call') as llm:
            result = service.make_plan(1, service.envelope(r, 1).report_token)
        retrieve.assert_not_called(); llm.assert_not_called()
        self.assertEqual(result.report.tasks, [])

    def test_invalid_urls_are_omitted_and_sources_are_bounded(self):
        invalid = {**HIT, 'metadata': {**HIT['metadata'], 'source_url': 'javascript:alert(1)'}}
        long_hit = {**HIT, 'content': '正文' * 2000}
        with patch('rag_chroma.retrieve', return_value=[invalid, long_hit, long_hit]):
            refs, states = collect_references(report().requirements[:1], time.monotonic() + 5)
        self.assertEqual(len(refs['r1']), 1)
        self.assertEqual(len(refs['r1'][0].excerpt), 600)
        self.assertEqual(states['r1'], 'available')

    def test_expired_budget_skips_retrieval(self):
        with patch('rag_chroma.retrieve') as retrieve:
            refs, states = collect_references(report().requirements[:1], time.monotonic() - 1)
        retrieve.assert_not_called()
        self.assertEqual(states['r1'], 'unavailable')

    def test_legacy_report_without_reference_fields_still_restores(self):
        r = report()
        r.tasks = [LearningTask(requirement_id='r1', objective='练习', actions=['实现'],
                                deliverable='代码', acceptance=['运行'])]
        value = r.model_dump()
        for key in ('references', 'reference_status', 'source_ids'):
            value['tasks'][0].pop(key)
        from career_models import CareerReport
        restored = CareerReport.model_validate(value)
        self.assertEqual(restored.tasks[0].references, [])


    def test_authenticated_plan_api_returns_reference_fields(self):
        from fastapi.testclient import TestClient
        import main
        main.app.dependency_overrides[main.get_current_user] = lambda: {'id': 1}
        self.addCleanup(main.app.dependency_overrides.clear)
        with patch('rag_chroma.retrieve', return_value=[HIT]), \
             patch('career_service.structured_call', side_effect=generate):
            response = TestClient(main.app).post('/career/plan', json={'report_token': self.token})
        self.assertEqual(response.status_code, 200)
        task = response.json()['report']['tasks'][0]
        self.assertEqual(task['reference_status'], 'cited')
        self.assertEqual(task['references'][0]['excerpt'], HIT['content'])

    def test_reference_count_is_bounded_even_if_retriever_returns_extra(self):
        hits = [{**HIT, 'content': str(i) + HIT['content']} for i in range(5)]
        with patch('rag_chroma.retrieve', return_value=hits):
            refs, _ = collect_references(report().requirements[:1], time.monotonic() + 5)
        self.assertEqual(len(refs['r1']), 2)
