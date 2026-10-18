"""Offline orchestration regressions: retain analysis even if optional planning fails."""
import copy
import unittest
from unittest.mock import Mock, call

from career_workflow import run_review
from web_client import ApiError


RESUME = {"resume_text": "真实经历"}
JOB = {"company": "", "job_title": "", "jd_text": "岗位要求"}


def envelope(*, category="skill", status="gap", importance="required", token="review-token"):
    return {
        "report_token": token,
        "history_saved": True,
        "report": {
            "requirements": [{"id": "r1", "title": "接口开发", "category": category,
                              "status": status, "importance": importance}],
            "tasks": [],
        },
    }


def saved_state():
    return {"resume_id": 2, "job_description_id": 5,
            "saved_resume": copy.deepcopy(RESUME), "saved_job": copy.deepcopy(JOB)}


class ReviewWorkflowTests(unittest.TestCase):
    def test_default_only_analyzes_and_commits_current_context(self):
        state = saved_state()
        reviewed = envelope()
        api = Mock(return_value=reviewed)
        outcome = run_review(api, state, RESUME, JOB)
        api.assert_called_once_with("POST", "/career/review", {"resume_id": 2, "job_description_id": 5})
        self.assertEqual(outcome["plan_state"], "manual")
        self.assertEqual(state["career"], reviewed)
        self.assertEqual(state["career_context"], (RESUME, JOB))

    def test_new_sources_are_saved_before_review_and_plan(self):
        state = {}
        reviewed = envelope()
        planned = envelope(token="plan-token")
        planned["report"]["tasks"] = [{"requirement_id": "r1", "objective": "完成接口练习"}]
        api = Mock(side_effect=[{"id": 2}, {"id": 5}, reviewed, planned])
        stage = Mock()
        outcome = run_review(api, state, RESUME, JOB, auto_plan=True, on_stage=stage)
        self.assertEqual(api.call_args_list, [
            call("POST", "/resumes", RESUME),
            call("POST", "/job-descriptions", JOB),
            call("POST", "/career/review", {"resume_id": 2, "job_description_id": 5}),
            call("POST", "/career/advance", {"report_token": "review-token"}),
        ])
        self.assertEqual(outcome["plan_state"], "complete")
        self.assertEqual(state["career"], planned)
        self.assertEqual(state["saved_resume"], RESUME)
        self.assertEqual(state["saved_job"], JOB)
        self.assertEqual(state["career_context"], (RESUME, JOB))
        self.assertTrue(stage.called)

    def test_only_changed_source_is_saved(self):
        state = saved_state()
        changed = dict(JOB, jd_text="修改后的岗位要求")
        api = Mock(side_effect=[{"id": 6}, envelope()])
        run_review(api, state, RESUME, changed)
        self.assertEqual(api.call_args_list, [
            call("POST", "/job-descriptions", changed),
            call("POST", "/career/review", {"resume_id": 2, "job_description_id": 6}),
        ])
        self.assertEqual(state["saved_job"], changed)

    def test_plan_failure_preserves_successful_analysis_and_context(self):
        state = saved_state()
        state["career"] = envelope(token="old-token")
        reviewed = envelope()

        def request(method, path, data):
            if path == "/career/review":
                return reviewed
            self.assertEqual(state["career"], reviewed, "Review must be stored before planning begins")
            self.assertEqual(state["career_context"], (RESUME, JOB))
            raise ApiError("行动计划暂时不可用", 502)

        api = Mock(side_effect=request)
        outcome = run_review(api, state, RESUME, JOB, auto_plan=True)
        self.assertEqual(outcome["plan_state"], "failed")
        self.assertEqual(outcome["plan_error"], "行动计划暂时不可用")
        self.assertEqual(state["career"], reviewed)
        self.assertEqual(api.call_count, 2, "Optional planning must not automatically retry writes")

    def test_plan_auth_failure_is_raised_for_login_handler(self):
        state = saved_state()
        reviewed = envelope()
        api = Mock(side_effect=[reviewed, ApiError("登录已过期", 401)])
        with self.assertRaises(ApiError) as caught:
            run_review(api, state, RESUME, JOB, auto_plan=True)
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(state["career"], reviewed)
        self.assertEqual(api.call_count, 2)

    def test_auto_mode_delegates_non_trainable_and_supported_requirements_to_agent(self):
        for row in (
            {"status": "supported"},
            {"importance": "example"},
            {"category": "qualification"},
            {"category": "language"},
        ):
            with self.subTest(row=row):
                state = saved_state()
                reviewed = envelope(**row)
                finished = envelope(**row, token="finished-token")
                finished['report']['agent'] = {'enabled': True, 'status': 'complete', 'note': '无需练习'}
                api = Mock(side_effect=[reviewed, finished])
                outcome = run_review(api, state, RESUME, JOB, auto_plan=True)
                self.assertEqual(outcome["plan_state"], "skipped")
                self.assertEqual(api.call_count, 2)
                self.assertEqual(api.call_args, call("POST", "/career/advance", {"report_token": "review-token"}))
                self.assertEqual(state['career'], finished)

    def test_auto_mode_delegates_empty_requirements_to_agent(self):
        reviewed = envelope()
        reviewed["report"]["requirements"] = []
        finished = copy.deepcopy(reviewed)
        finished['report']['agent'] = {'enabled': True, 'status': 'complete', 'note': '没有待处理要求'}
        api = Mock(side_effect=[reviewed, finished])
        outcome = run_review(api, saved_state(), RESUME, JOB, auto_plan=True)
        self.assertEqual(outcome["plan_state"], "skipped")
        self.assertEqual(api.call_count, 2)

    def test_unknown_and_partial_practice_can_request_optional_plan(self):
        for status in ("unknown", "partial"):
            with self.subTest(status=status):
                reviewed = envelope(category="experience", status=status)
                planned = envelope(category="experience", status=status, token="plan-token")
                api = Mock(side_effect=[reviewed, planned])
                outcome = run_review(api, saved_state(), RESUME, JOB, auto_plan=True)
                self.assertEqual(outcome["plan_state"], "complete")
                self.assertEqual(api.call_args_list[-1], call("POST", "/career/advance", {"report_token": "review-token"}))

    def test_manual_mode_without_plan_candidates_skips_without_advancing(self):
        for row in ({'status': 'supported'}, {'importance': 'example'}, {'category': 'qualification'}):
            with self.subTest(row=row):
                api = Mock(return_value=envelope(**row))
                outcome = run_review(api, saved_state(), RESUME, JOB)
                self.assertEqual(outcome['plan_state'], 'skipped')
                self.assertEqual(api.call_count, 1)

    def test_waiting_agent_preserves_clarification_and_stops_without_repeated_call(self):
        state = saved_state()
        reviewed = envelope(category='qualification', status='unknown')
        waiting = envelope(category='qualification', status='unknown', token='waiting-token')
        waiting['report']['agent'] = {'enabled': True, 'status': 'waiting', 'note': '请补充毕业学历。'}
        waiting['report']['messages'] = [{'role': 'assistant', 'content': '请补充毕业学历。'}]
        api = Mock(side_effect=[reviewed, waiting])
        outcome = run_review(api, state, RESUME, JOB, auto_plan=True)
        self.assertEqual(outcome['plan_state'], 'waiting')
        self.assertEqual(state['career'], waiting)
        self.assertEqual(state['career_context'], (RESUME, JOB))
        self.assertEqual(api.call_count, 2)

    def test_failed_agent_envelope_retains_latest_report_and_reason(self):
        state = saved_state()
        reviewed = envelope()
        failed = envelope(token='failed-token')
        failed['report']['agent'] = {'enabled': True, 'status': 'failed', 'note': '参考资料暂不可用，请稍后重试。'}
        api = Mock(side_effect=[reviewed, failed])
        outcome = run_review(api, state, RESUME, JOB, auto_plan=True)
        self.assertEqual(outcome['plan_state'], 'failed')
        self.assertEqual(outcome['plan_error'], failed['report']['agent']['note'])
        self.assertEqual(state['career'], failed)
        self.assertEqual(api.call_count, 2)

    def test_completed_agent_maps_plan_availability_and_legacy_idle_response(self):
        for agent_status, has_tasks, expected in (
            ('complete', True, 'complete'), ('complete', False, 'skipped'),
            ('idle', False, 'complete'), (None, False, 'complete'),
        ):
            with self.subTest(agent_status=agent_status, has_tasks=has_tasks):
                advanced = envelope(token='advanced-token')
                if agent_status is not None:
                    advanced['report']['agent'] = {'enabled': True, 'status': agent_status, 'note': ''}
                if has_tasks:
                    advanced['report']['tasks'] = [{'requirement_id': 'r1', 'objective': '练习接口'}]
                api = Mock(side_effect=[envelope(), advanced])
                state = saved_state()
                outcome = run_review(api, state, RESUME, JOB, auto_plan=True)
                self.assertEqual(outcome['plan_state'], expected)
                self.assertEqual(state['career'], advanced)

    def test_source_save_failure_stops_review_and_keeps_prior_saved_source(self):
        state = {}
        api = Mock(side_effect=[{"id": 2}, ApiError("保存岗位未完成", 503)])
        with self.assertRaises(ApiError):
            run_review(api, state, RESUME, JOB, auto_plan=True)
        self.assertEqual([c.args[1] for c in api.call_args_list], ["/resumes", "/job-descriptions"])
        self.assertEqual(state["resume_id"], 2)
        self.assertEqual(state["saved_resume"], RESUME)
        self.assertNotIn("career", state)
        self.assertNotIn("job_description_id", state)

    def test_failed_review_retry_reuses_both_saved_sources(self):
        state = {}
        first = Mock(side_effect=[{"id": 2}, {"id": 5}, ApiError("分析暂时不可用", 502)])
        with self.assertRaises(ApiError):
            run_review(first, state, RESUME, JOB, auto_plan=True)
        self.assertNotIn("career", state)
        retry = Mock(return_value=envelope())
        run_review(retry, state, RESUME, JOB)
        retry.assert_called_once_with("POST", "/career/review", {"resume_id": 2, "job_description_id": 5})

    def test_review_auth_error_propagates_without_plan(self):
        api = Mock(side_effect=ApiError("登录已过期", 401))
        with self.assertRaises(ApiError) as caught:
            run_review(api, saved_state(), RESUME, JOB, auto_plan=True)
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(api.call_count, 1)


if __name__ == "__main__":
    unittest.main()
