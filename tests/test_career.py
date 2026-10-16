"""Fixed offline cases for evidence scoring, chat confirmation and target separation."""
import os
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['JWT_SECRET_KEY']='test-only-secret-that-is-at-least-32-bytes-long'
import unittest
from unittest.mock import patch
from io import BytesIO
import zipfile
from career_models import (RequirementDraft, RequirementsDraft, Requirement, CareerReport,
                          CoachReply, Proposal, LearningDraft, LearningTask)
from assessment_service import assess, metrics
import career_service as service
from file_import import extract_text
from fastapi.testclient import TestClient
import main

RESUME='使用 Python 和 Flask 开发后端接口。英语 CET-4。'
JD='熟悉 Python 后端开发，RAG经验优先，英语六级或同等水平。'


def row(id='r1',**kwargs):
    data=dict(id=id,title='Python',category='skill',importance='required',jd_quote='熟悉 Python 后端开发',
              status='unknown',resume_quotes=[],explanation='待确认',question='做过什么？',weight=3,points=0)
    data.update(kwargs)
    return Requirement(**data)


def report():
    return CareerReport(resume_id=2,job_description_id=5,source_hash=service.fingerprint(RESUME,JD),
        requirements=[row(),row('r2',title='RAG',importance='preferred',weight=1,jd_quote='RAG经验优先'),
                      row('r3',title='英语',category='language',jd_quote='英语六级或同等水平')],score=0,evidence_coverage=0)


class AssessmentTests(unittest.TestCase):
    def test_fixed_weights_unknown_is_not_a_proven_gap(self):
        rows=[row(status='supported'),row('r2',importance='preferred',weight=1,status='partial'),
              row('r3',weight=0,importance='example',status='gap')]
        score,coverage=metrics(rows)
        self.assertEqual(score,88)
        self.assertEqual(coverage,100)
        rows[0].status='unknown'
        self.assertEqual(metrics(rows),(12,25))

    def test_invalid_resume_evidence_downgrades_to_unknown(self):
        draft=RequirementsDraft(requirements=[RequirementDraft(title='Python',category='skill',importance='required',
            jd_quote='熟悉 Python 后端开发',status='supported',resume_quotes=['不存在的经历'],explanation='已经会')])
        with patch('assessment_service.structured_call',return_value=draft):
            rows,score,coverage,warnings=assess(RESUME,JD)
        self.assertEqual(rows[0].status,'unknown')
        self.assertEqual(score,0)
        self.assertTrue(warnings)

    def test_jd_evidence_retries_then_rejects(self):
        draft=RequirementsDraft(requirements=[RequirementDraft(title='Python',category='skill',importance='required',
            jd_quote='编造的要求',status='unknown',explanation='待确认')])
        with patch('assessment_service.structured_call',return_value=draft) as model:
            with self.assertRaises(ValueError): assess(RESUME,JD)
        self.assertEqual(model.call_count,2)


class CareerTests(unittest.TestCase):
    def setUp(self):
        self.sources=patch('career_service.source_text',return_value=(RESUME,JD))
        self.sources.start();self.addCleanup(self.sources.stop)
        self.token=service.envelope(report(),1).report_token

    def test_report_is_account_bound_and_signature_checked(self):
        with self.assertRaises(service.ReportError): service.restore(self.token,2)
        with self.assertRaises(service.ReportError): service.restore(self.token+'tampered',1)
        self.assertEqual(service.restore(self.token,1)[0].score,0)

    def test_source_change_invalidates_report(self):
        with patch('career_service.source_text',return_value=(RESUME+'new',JD)):
            with self.assertRaises(service.ReportError): service.restore(self.token,1)

    def test_chat_does_not_change_score_before_confirmation(self):
        message='我使用 Python 实现过后端接口，处理了参数校验和接口异常。'
        reply=CoachReply(answer='请确认补充',proposals=[Proposal(requirement_id='r1',status='supported',statement=message,reason='提供了实际实现')])
        with patch('career_service.structured_call',return_value=reply):
            result=service.chat(1,self.token,message)
        self.assertEqual(result.report.score,0)
        confirmed=service.confirm(1,result.report_token,0,True)
        self.assertGreater(confirmed.report.score,0)
        self.assertEqual(confirmed.report.requirements[0].source,'user_confirmed')
        self.assertEqual(confirmed.report.requirements[0].user_statement,message)

    def test_planned_learning_cannot_be_promoted_as_acquired(self):
        message='假设我已经学习了 Python 并实现接口，能否帮我完善简历？'
        reply=CoachReply(answer='这是未来假设',proposals=[Proposal(requirement_id='r1',status='supported',statement=message,reason='模型误判')])
        with patch('career_service.structured_call',return_value=reply):
            result=service.chat(1,self.token,message)
        self.assertEqual(result.report.pending,[])
        self.assertEqual(result.report.score,0)

    def test_fake_quote_and_unknown_requirement_are_ignored(self):
        reply=CoachReply(answer='test',proposals=[Proposal(requirement_id='r1',status='gap',statement='没有学过',reason='x'),
            Proposal(requirement_id='unknown',status='gap',statement='test',reason='x')])
        with patch('career_service.structured_call',return_value=reply):
            result=service.chat(1,self.token,'test')
        self.assertEqual(result.report.pending,[])

    def test_rejection_does_not_modify_requirement(self):
        r=report();r.pending=[Proposal(requirement_id='r1',status='gap',statement='没有学过Python',reason='自述')]
        result=service.confirm(1,service.envelope(r,1).report_token,0,False)
        self.assertEqual(result.report.requirements[0].status,'unknown')
        self.assertEqual(result.report.pending,[])

    def test_plan_covers_skills_and_excludes_language(self):
        tasks=[LearningTask(requirement_id=i,objective='实践后端功能',actions=['实现接口','添加错误处理'],
                            deliverable='代码和演示',acceptance=['错误输入有明确返回']) for i in ('r1','r2')]
        with patch('career_service.structured_call',return_value=LearningDraft(tasks=tasks)) as model:
            result=service.make_plan(1,self.token)
        self.assertEqual([t.requirement_id for t in result.report.tasks],['r1','r2'])
        self.assertEqual({r['id'] for r in model.call_args.args[2]['requirements']},{'r1','r2'})

    def test_confirmation_invalidates_old_plan(self):
        r=report();r.pending=[Proposal(requirement_id='r1',status='gap',statement='尚未学习Python',reason='自述')]
        r.tasks=[LearningTask(requirement_id='r1',objective='学习',actions=['实现'],deliverable='代码',acceptance=['运行'])]
        result=service.confirm(1,service.envelope(r,1).report_token,0,True)
        self.assertEqual(result.report.tasks,[])

    def test_target_is_marked_and_never_saved_as_optimization(self):
        with patch('repositories.save_optimization_result') as save:
            result=service.target_resume(1,self.token)
        self.assertTrue(result['is_target'])
        self.assertIn('待完成',result['text'])
        self.assertIn(RESUME,result['text'])
        save.assert_not_called()

    def test_only_confirmed_actual_statements_enter_new_resume(self):
        r=report();r.requirements[0].source='user_confirmed';r.requirements[0].status='supported'
        r.requirements[0].user_statement='我用 Python 开发过接口并处理参数异常。'
        r.requirements[1].source='user_confirmed';r.requirements[1].status='gap';r.requirements[1].user_statement='计划学习RAG'
        with patch('repositories.create_resume_text',return_value=9) as create:
            result=service.promote(1,service.envelope(r,1).report_token)
        self.assertIn('处理参数异常',result['resume_text'])
        self.assertNotIn('计划学习RAG',result['resume_text'])
        create.assert_called_once_with(1,result['resume_text'])

    def test_no_confirmed_fact_does_not_write(self):
        with patch('repositories.create_resume_text') as create:
            with self.assertRaises(service.ReportError): service.promote(1,self.token)
        create.assert_not_called()


class ImportTests(unittest.TestCase):
    def test_plain_text(self):
        self.assertEqual(extract_text('简历.txt','真实经历'.encode()),'真实经历')

    def test_docx_extracts_text_without_writing_files(self):
        memory=BytesIO()
        with zipfile.ZipFile(memory,'w') as archive:
            archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>测试经历</w:t></w:r></w:p></w:body></w:document>')
        self.assertEqual(extract_text('x.docx',memory.getvalue()),'测试经历')

    def test_scanned_or_empty_pdf_has_clear_error(self):
        import sys
        from pathlib import Path
        sys.path.append(str(Path(__file__).resolve().parents[1]/'.web-libs'))
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(width=100,height=100)
        memory=BytesIO();writer.write(memory)
        with self.assertRaisesRegex(ValueError,'没有提取到文字'):
            extract_text('blank.pdf',memory.getvalue())


class CareerApiTests(unittest.TestCase):
    def tearDown(self): main.app.dependency_overrides.clear()

    def test_requires_authentication(self):
        result=TestClient(main.app).post('/career/review',json={'resume_id':2,'job_description_id':5})
        self.assertIn(result.status_code,(401,403))

    def test_report_access_checks_identity(self):
        main.app.dependency_overrides[main.get_current_user]=lambda:{'id':2}
        token=service.envelope(report(),1).report_token
        with patch('career_service.source_text') as source:
            response=TestClient(main.app).post('/career/target',json={'report_token':token})
        self.assertEqual(response.status_code,409)
        source.assert_not_called()
