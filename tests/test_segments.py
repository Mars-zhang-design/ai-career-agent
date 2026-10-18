"""Fixed, fictional evaluation cases; never sent to a real provider."""
import os
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['JWT_SECRET_KEY']='test-only-secret-that-is-at-least-32-bytes-long'
import unittest
from unittest.mock import patch
from schemas import SegmentRewritePlan
from segment_rewriter import split_segments, validate_plan, assemble_resume
from resume_optimizer import optimize_resume, UnsafeOptimization, NoEffectiveOptimization

ORIGINAL='基于 Flask 使用 Python 编写后端逻辑，采用 MySQL 存储数据，独立处理接口异常，提升了问题解决能力。'
REWRITTEN='使用 Python 和 Flask 开发后端逻辑，通过 MySQL 存储数据，并独立排查接口异常。'
JD='岗位要求：使用 Python 开发后端服务，处理接口异常。'
RESUME='测试姓名\r\n\r\n项目经历\r\n'+ORIGINAL+'\r\n英语：CET-4\r\n'
ANALYSIS={'match_score':60,'matched_skills':['Python'],'missing_skills':['RAG'],'jd_keywords':['Python'],'warnings':[]}


def make_plan(**overrides):
    edit={'segment_id':3,'optimized':REWRITTEN,'issue':'技术实现和自我评价混写',
          'reason':'突出后端开发和异常排查的具体职责','evidence':['使用 Python 编写后端逻辑','独立处理接口异常'],
          'jd_evidence':'使用 Python 开发后端服务'}
    edit.update(overrides)
    return SegmentRewritePlan(edits=[edit])


class SegmentTests(unittest.TestCase):
    def setUp(self):
        self.segments=split_segments(RESUME)

    def test_exact_assembly_preserves_unedited_text_and_line_endings(self):
        plan=make_plan()
        self.assertEqual(validate_plan(self.segments,plan,JD),[])
        final,suggestions=assemble_resume(RESUME,self.segments,plan)
        self.assertEqual(final,RESUME.replace(ORIGINAL,REWRITTEN))
        self.assertEqual(suggestions[0]['original'],ORIGINAL)
        self.assertEqual(suggestions[0]['evidence'],plan.edits[0].evidence)

    def test_repeated_paragraphs_have_distinct_offsets(self):
        source=ORIGINAL+'\n'+ORIGINAL
        plan=make_plan(segment_id=2)
        final,_=assemble_resume(source,split_segments(source),plan)
        self.assertEqual(final,ORIGINAL+'\n'+REWRITTEN)

    def test_reject_fabricated_original_evidence(self):
        self.assertTrue(validate_plan(self.segments,make_plan(evidence=['完成 RAG 平台']),JD))

    def test_reject_fabricated_job_evidence(self):
        self.assertTrue(validate_plan(self.segments,make_plan(jd_evidence='精通 LangGraph'),JD))

    def test_reject_evidence_from_other_paragraph(self):
        self.assertTrue(validate_plan(self.segments,make_plan(evidence=['CET-4']),JD))

    def test_reject_unknown_and_protected_segments(self):
        for segment_id in (999,1):
            with self.subTest(segment_id=segment_id):
                self.assertTrue(validate_plan(self.segments,make_plan(segment_id=segment_id),JD))

    def test_reject_added_metrics(self):
        self.assertTrue(validate_plan(self.segments,make_plan(optimized=REWRITTEN+'效率提升50%。'),JD))

    def test_reject_lowering_or_raising_proficiency(self):
        source='熟悉 Python，使用 Flask 开发后端服务，采用 MySQL 存储业务数据。'
        segments=split_segments(source)
        for level in ('精通','了解'):
            with self.subTest(level=level):
                plan=make_plan(segment_id=1,optimized=source.replace('熟悉',level),evidence=['熟悉 Python'])
                self.assertTrue(validate_plan(segments,plan,JD))

    def test_reject_duplicate_and_multiline_edits(self):
        plan=make_plan();plan.edits.append(plan.edits[0])
        self.assertTrue(validate_plan(self.segments,plan,JD))
        self.assertTrue(validate_plan(self.segments,make_plan(optimized=REWRITTEN+'\n另一段'),JD))

    def test_success_returns_reason_and_grounded_evidence(self):
        with patch('resume_optimizer.structured_call',return_value=make_plan()) as model:
            result=optimize_resume(RESUME,JD,ANALYSIS)
        model.assert_called_once()
        self.assertEqual(result['optimized_resume'],RESUME.replace(ORIGINAL,REWRITTEN))
        self.assertEqual(result['rewrite_suggestions'][0]['reason'],'突出后端开发和异常排查的具体职责')
        self.assertEqual(result['match_score'],60)

    def test_invalid_plan_is_repaired_with_specific_feedback(self):
        with patch('resume_optimizer.structured_call',side_effect=[make_plan(evidence=['不存在的经历']),make_plan()]) as model:
            result=optimize_resume(RESUME,JD,ANALYSIS)
        self.assertEqual(model.call_count,2)
        self.assertTrue(model.call_args.args[2]['validation_feedback'])
        self.assertEqual(result['optimized_resume'],RESUME.replace(ORIGINAL,REWRITTEN))

    def test_two_invalid_plans_fail_instead_of_returning_output(self):
        with patch('resume_optimizer.structured_call',return_value=make_plan(jd_evidence='捏造要求')) as model:
            with self.assertRaises(UnsafeOptimization):
                optimize_resume(RESUME,JD,ANALYSIS)
        self.assertEqual(model.call_count,2)

    def test_two_copies_fail_without_force_rewrite(self):
        with patch('resume_optimizer.structured_call',return_value=make_plan(optimized=ORIGINAL)) as model:
            with self.assertRaises(NoEffectiveOptimization):
                optimize_resume(RESUME,JD,ANALYSIS)
        self.assertEqual(model.call_count,2)


    def test_general_polish_does_not_require_job_evidence(self):
        from schemas import GeneralRewritePlan
        data=make_plan().model_dump();data['edits'][0]['jd_evidence']=''
        plan=GeneralRewritePlan.model_validate(data)
        with patch('resume_optimizer.structured_call',return_value=plan) as model:
            result=optimize_resume(RESUME,'通用表达标准',ANALYSIS,mode='general')
        self.assertEqual(model.call_args.args[0],GeneralRewritePlan)
        self.assertEqual(model.call_args.args[2]['analysis'],{})
        self.assertEqual(model.call_args.args[2]['job_description'],'')
        self.assertEqual(result['optimized_resume'],RESUME.replace(ORIGINAL,REWRITTEN))
        self.assertEqual(result['rewrite_suggestions'][0]['jd_evidence'],'')
        self.assertTrue(validate_plan(self.segments,plan,JD))

    def test_existing_partial_skill_is_not_rejected(self):
        analysis={**ANALYSIS,'missing_skills':['Python']}
        with patch('resume_optimizer.structured_call',return_value=make_plan()):
            result=optimize_resume(RESUME,JD,analysis,mode='general')
        self.assertIn('Python',result['optimized_resume'])

    def test_missing_skill_cannot_be_added_or_borrowed(self):
        from resume_optimizer import validate_resume_result
        for source in (RESUME,RESUME+'\n其他项目：RAG'):
            result={'match_score':60,'missing_skills':['RAG'],
                    'optimized_resume':source.replace(ORIGINAL,REWRITTEN+'完成RAG。'),
                    'rewrite_suggestions':[{'original':ORIGINAL,'optimized':REWRITTEN+'完成RAG。'}]}
            self.assertTrue(validate_resume_result(source,result))

    def test_general_mode_keeps_numbers_proficiency_and_evidence_checks(self):
        for overrides in ({'optimized':REWRITTEN+'提升50%。'},
                          {'optimized':'精通Python。'+REWRITTEN},
                          {'evidence':['虚构个人经历']}):
            with self.subTest(overrides=overrides):
                with patch('resume_optimizer.structured_call',return_value=make_plan(**overrides)):
                    with self.assertRaises(UnsafeOptimization) as caught:
                        optimize_resume(RESUME,'通用表达标准',ANALYSIS,mode='general')
                self.assertTrue(caught.exception.reasons)
