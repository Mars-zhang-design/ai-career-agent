"""Offline regressions for bounded, human-confirmed career orchestration."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

import career_agent as agent
import career_service as service
import main
from auth_service import JWT_SECRET_KEY
from career_models import CareerReport, ChatMessage, CoachReply, LearningTask, Proposal, Requirement


RESUME = "使用 Python 实现接口、参数校验和错误处理。"
JD = "熟悉 Python 后端开发，了解 RAG 检索与评估。"


def requirement(identity="r1", **overrides):
    data = dict(id=identity, title="Python " + identity, category="skill", importance="required",
                jd_quote="熟悉 Python 后端开发", status="unknown", resume_quotes=[],
                explanation="简历证据不足", question="请说明实际做过的项目。", weight=3, points=0)
    data.update(overrides)
    return Requirement(**data)


def report(rows=None):
    return CareerReport(resume_id=2, job_description_id=5,
                        source_hash=service.fingerprint(RESUME, JD),
                        requirements=rows if rows is not None else [requirement()],
                        score=0, evidence_coverage=0,
                        messages=[ChatMessage(role="assistant", content="请补充实际经历。")])


def task(row, **overrides):
    data = dict(requirement_id=row.id, objective="实现可运行接口", actions=["实现参数校验"],
                deliverable="代码和测试报告", acceptance=["无效参数返回明确错误"], basis=agent.basis(row))
    data.update(overrides)
    return LearningTask(**data)


def no_references(rows, deadline):
    return ({row.id: [] for row in rows}, {row.id: "empty" for row in rows})


def generated_tasks(rows, jd, references, states, deadline, **kwargs):
    return [task(row) for row in rows]


class CareerAgentTests(unittest.TestCase):
    def setUp(self):
        self.source = patch("career_service.source_text", return_value=(RESUME, JD))
        self.source.start()
        self.addCleanup(self.source.stop)
        self.route_patch = patch("career_agent.structured_call")
        self.route = self.route_patch.start()
        self.addCleanup(self.route_patch.stop)
        self.retrieval_patch = patch("career_agent.collect_references", side_effect=no_references)
        self.retrieval = self.retrieval_patch.start()
        self.addCleanup(self.retrieval_patch.stop)
        self.generate_patch = patch("career_agent.generate_tasks", side_effect=generated_tasks)
        self.generate = self.generate_patch.start()
        self.addCleanup(self.generate_patch.stop)

    def advance(self, value, **kwargs):
        return service.advance(1, service.envelope(value, 1).report_token, **kwargs).report

    def assert_no_tools(self):
        self.route.assert_not_called()
        self.retrieval.assert_not_called()
        self.generate.assert_not_called()

    def test_legacy_signed_report_restores_with_safe_agent_defaults(self):
        legacy = report().model_dump()
        legacy.pop("agent")
        token = jwt.encode({"kind": "career_report", "sub": "1", "report": legacy,
                            "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                           JWT_SECRET_KEY, algorithm="HS256")
        restored, _, _ = service.restore(token, 1)
        self.assertFalse(restored.agent.enabled)
        self.assertEqual(restored.agent.clarification_rounds, 0)
        self.assertEqual(restored.agent.evidence, [])
        self.assert_no_tools()

    def test_unknown_clarification_is_bounded_and_repeated_advance_waits(self):
        original = report([requirement("r1"), requirement("r2"), requirement("r3")])
        first = self.advance(original)
        self.assertEqual(first.agent.status, "waiting")
        self.assertEqual(first.agent.next_action, "clarify")
        self.assertLessEqual(len(first.agent.focus_ids), 2)
        self.assertTrue(first.agent.focus_ids)
        self.assertEqual(len(first.messages), 1, "The initial generic question must not be duplicated")
        second = self.advance(first)
        self.assertEqual(second.messages, first.messages)
        self.assertEqual(second.agent.focus_ids, first.agent.focus_ids)
        self.assertEqual([r.model_dump() for r in second.requirements], [r.model_dump() for r in original.requirements])
        self.assertEqual(second.score, original.score)
        self.assert_no_tools()

    def test_skip_clarification_plans_without_claiming_missing_or_acquired_skill(self):
        original = report([requirement("r1"), requirement("r2")])
        waiting = self.advance(original)
        result = self.advance(waiting, skip_clarification=True)
        self.assertEqual([r.status for r in result.requirements], ["unknown", "unknown"])
        self.assertEqual([r.user_statement for r in result.requirements], ["", ""])
        self.assertEqual(result.score, original.score)
        self.assertEqual({t.requirement_id for t in result.tasks}, {"r1", "r2"})
        self.assertEqual(result.agent.status, "complete")
        self.assertEqual(result.agent.clarification_rounds, 1)
        self.route.assert_not_called()
        self.retrieval.assert_called_once()
        self.generate.assert_called_once()

    def test_pending_proposals_always_wait_for_human_even_when_skipping(self):
        original = report([requirement(status="gap")])
        original.pending = [Proposal(requirement_id="r1", status="supported",
                                     statement="我实现了接口参数校验和异常处理。", reason="待用户核对")]
        result = self.advance(original, skip_clarification=True)
        self.assertEqual(result.agent.next_action, "confirm")
        self.assertEqual(result.agent.status, "waiting")
        self.assertEqual(result.pending, original.pending)
        self.assertEqual(result.requirements, original.requirements)
        self.assert_no_tools()

    def test_ordinary_chat_preserves_pending_confirmation_and_consistent_wait_state(self):
        original = report()
        original.agent.enabled = True
        original.agent.status, original.agent.next_action = "waiting", "confirm"
        original.pending = [Proposal(requirement_id="r1", status="gap", statement="尚未做过接口开发", reason="待本人核对")]
        with patch("career_service.structured_call", return_value=CoachReply(answer="可以先查看改善方向。", proposals=[])):
            result = service.chat(1, service.envelope(original, 1).report_token, "先讲讲学习方向").report
        self.assertEqual(result.pending, original.pending)
        self.assertEqual(result.agent.status, "waiting")
        self.assertEqual(result.agent.next_action, "confirm")
        self.assertEqual(result.requirements, original.requirements)
        self.assert_no_tools()

    def test_chat_replaces_only_same_requirement_proposal_and_keeps_others_pending(self):
        original = report([requirement("r1"), requirement("r2")])
        original.agent.enabled = True
        original.agent.status, original.agent.next_action = "waiting", "confirm"
        original.pending = [Proposal(requirement_id="r1", status="gap", statement="未做过接口开发", reason="较早补充"),
                            Proposal(requirement_id="r2", status="gap", statement="未实现过检索评估", reason="待本人核对")]
        message = "我补充一下：用 Python 实现了查询接口，并添加了参数校验和异常处理。"
        newest = Proposal(requirement_id="r1", status="partial", statement=message, reason="新的具体经历")
        with patch("career_service.structured_call", return_value=CoachReply(answer="请核对新的补充。", proposals=[newest])):
            result = service.chat(1, service.envelope(original, 1).report_token, message).report
        proposals = {item.requirement_id: item for item in result.pending}
        self.assertEqual(len(result.pending), 2)
        self.assertEqual(proposals["r1"], newest)
        self.assertEqual(proposals["r2"], original.pending[1])
        self.assertEqual(result.agent.status, "waiting")
        self.assertEqual(result.agent.next_action, "confirm")
        self.assertEqual(result.requirements, original.requirements)
        self.assert_no_tools()

    def test_supported_report_finishes_without_decision_retrieval_or_generation(self):
        original = report([requirement(status="supported", resume_quotes=[RESUME])])
        result = self.advance(original)
        self.assertEqual(result.agent.status, "complete")
        self.assertEqual(result.agent.next_action, "done")
        self.assertEqual(result.tasks, [])
        self.assert_no_tools()

    def test_hard_conditions_and_examples_do_not_generate_practice_tasks(self):
        original = report([requirement("r1", category="qualification", status="gap"),
                           requirement("r2", category="language", status="partial"),
                           requirement("r3", importance="example", status="gap", weight=0)])
        result = self.advance(original)
        self.assertEqual(result.tasks, [])
        self.assertEqual(result.agent.next_action, "done")
        self.assert_no_tools()

    def test_known_gap_has_one_shared_deadline_and_no_routing_model_call(self):
        result = self.advance(report([requirement(status="gap")]))
        self.route.assert_not_called()
        self.retrieval.assert_called_once()
        self.generate.assert_called_once()
        self.assertEqual(self.retrieval.call_args.args[1], self.generate.call_args.args[4])
        self.assertEqual(result.agent.status, "complete")
        self.assertEqual(result.tasks[0].basis, agent.basis(result.requirements[0]))

    def test_mixed_evidence_model_can_prioritize_known_gap_then_stop_for_clarification(self):
        self.route.return_value = agent.RouteDecision(action="plan")
        result = self.advance(report([requirement("r1"), requirement("r2", status="gap")]))
        self.route.assert_called_once()
        self.assertEqual(self.route.call_args.kwargs["max_attempts"], 1)
        self.assertEqual({t.requirement_id for t in result.tasks}, {"r2"})
        self.assertEqual(result.agent.status, "waiting")
        self.assertEqual(result.agent.next_action, "clarify")
        self.assertEqual(result.agent.focus_ids, ["r1"])

    def test_invalid_model_action_falls_back_to_clarify_without_executing_it(self):
        self.route.return_value = {"action": "promote", "requirement_ids": ["other-user"]}
        result = self.advance(report([requirement("r1"), requirement("r2", status="gap")]))
        self.assertEqual(result.agent.next_action, "clarify")
        self.assertTrue(set(result.agent.focus_ids) <= {"r1"})
        self.assertEqual(result.tasks, [])
        self.retrieval.assert_not_called()
        self.generate.assert_not_called()
        self.assertTrue(any(step.outcome == "fallback" for step in result.agent.trace))

    def test_route_timeout_falls_back_without_leaking_provider_payload(self):
        self.route.side_effect = TimeoutError("PRIVATE_RESUME_SECRET")
        result = self.advance(report([requirement("r1"), requirement("r2", status="gap")]))
        self.assertEqual(result.agent.next_action, "clarify")
        self.assertNotIn("PRIVATE_RESUME_SECRET", result.model_dump_json())
        self.retrieval.assert_not_called()
        self.generate.assert_not_called()

    def test_existing_valid_tasks_are_reused_without_model_or_retrieval(self):
        original = report([requirement(status="gap")])
        original.tasks = [task(original.requirements[0])]
        result = self.advance(original)
        self.assertEqual(result.tasks, original.tasks)
        self.assertEqual(result.agent.status, "complete")
        self.assert_no_tools()

    def test_plan_failure_preserves_other_tasks_and_retries_only_failed_step(self):
        original = report([requirement("r1", status="gap"), requirement("r2", status="partial")])
        original.tasks = [task(original.requirements[0])]
        untouched = original.tasks[0].model_dump()
        self.generate.side_effect = TimeoutError("PRIVATE_INPUT_AND_PROVIDER_TEXT")
        failed = self.advance(original)
        self.assertEqual(failed.agent.status, "failed")
        self.assertEqual(failed.agent.next_action, "plan")
        self.assertEqual([t.model_dump() for t in failed.tasks], [untouched])
        self.assertEqual({e.requirement_id for e in failed.agent.evidence}, {"r2"})
        self.assertEqual([r.id for r in self.generate.call_args.args[0]], ["r2"])
        self.assertNotIn("PRIVATE_INPUT_AND_PROVIDER_TEXT", failed.model_dump_json())
        self.retrieval.reset_mock()
        self.generate.reset_mock()
        self.generate.side_effect = generated_tasks
        retried = self.advance(failed)
        self.retrieval.assert_not_called()
        self.generate.assert_called_once()
        self.assertEqual([r.id for r in self.generate.call_args.args[0]], ["r2"])
        self.assertEqual(next(t.model_dump() for t in retried.tasks if t.requirement_id == "r1"), untouched)
        self.assertEqual(retried.agent.status, "complete")

    def test_confirm_only_invalidates_changed_requirement_and_keeps_other_task(self):
        original = report([requirement("r1", status="partial"), requirement("r2", status="gap")])
        original.agent.enabled = True
        original.tasks = [task(row) for row in original.requirements]
        original.pending = [Proposal(requirement_id="r1", status="gap", statement="我没有实现过接口参数校验。", reason="用户补充")]
        untouched = original.tasks[1].model_dump()
        confirmed = service.confirm(1, service.envelope(original, 1).report_token, 0, True).report
        self.assertEqual([t.model_dump() for t in confirmed.tasks], [untouched])
        advanced = self.advance(confirmed)
        self.assertEqual([r.id for r in self.generate.call_args.args[0]], ["r1"])
        self.assertEqual(next(t.model_dump() for t in advanced.tasks if t.requirement_id == "r2"), untouched)

    def test_rejection_keeps_tasks_and_never_regenerates_unchanged_work(self):
        original = report([requirement(status="gap")])
        original.agent.enabled = True
        original.tasks = [task(original.requirements[0])]
        original.pending = [Proposal(requirement_id="r1", status="supported", statement="不准确的补充经历", reason="待核对")]
        rejected = service.confirm(1, service.envelope(original, 1).report_token, 0, False).report
        advanced = self.advance(rejected)
        self.assertEqual(advanced.tasks, original.tasks)
        self.assertEqual(advanced.requirements, original.requirements)
        self.assert_no_tools()

    def test_step_limit_returns_recoverable_result_without_tool_execution(self):
        with patch.object(agent, "MAX_STEPS", 0):
            result = self.advance(report([requirement(status="gap")]))
        self.assertEqual(result.agent.status, "failed")
        self.assertEqual(result.tasks, [])
        self.assert_no_tools()

    def test_expired_budget_stops_before_retrieval_or_generation(self):
        with patch.object(agent, "RUN_SECONDS", 0):
            result = self.advance(report([requirement(status="gap")]))
        self.assertEqual(result.agent.status, "failed")
        self.assertEqual(result.tasks, [])
        self.assert_no_tools()

    def test_unrelated_generated_batch_is_rejected_atomically(self):
        original = report([requirement("r1", status="gap"), requirement("r2", status="partial")])
        original.tasks = [task(original.requirements[0])]
        self.generate.side_effect = None
        self.generate.return_value = [task(requirement("foreign", status="gap"))]
        result = self.advance(original)
        self.assertEqual(result.agent.status, "failed")
        self.assertEqual(result.tasks, original.tasks)
        self.assertEqual(result.requirements, original.requirements)
        self.assertEqual(result.score, original.score)
        self.assertEqual({e.requirement_id for e in result.agent.evidence}, {"r2"})


class CareerAgentApiTests(unittest.TestCase):
    def setUp(self):
        main.app.dependency_overrides.clear()
        self.addCleanup(main.app.dependency_overrides.clear)
        self.save = patch("career_api.save_snapshot", return_value=101)
        self.snapshot = self.save.start()
        self.addCleanup(self.save.stop)
        self.client = TestClient(main.app)

    def test_advance_requires_login(self):
        response = self.client.post("/career/advance", json={"report_token": "unsigned"})
        self.assertIn(response.status_code, (401, 403))
        self.snapshot.assert_not_called()

    def test_advance_rejects_other_account_before_loading_sources_or_tools(self):
        main.app.dependency_overrides[main.get_current_user] = lambda: {"id": 2}
        with patch("career_service.source_text") as source, patch("career_agent.run") as run:
            response = self.client.post("/career/advance", json={"report_token": service.envelope(report(), 1).report_token})
        self.assertEqual(response.status_code, 409)
        source.assert_not_called()
        run.assert_not_called()
        self.snapshot.assert_not_called()

    def test_tampered_report_cannot_invoke_tools(self):
        main.app.dependency_overrides[main.get_current_user] = lambda: {"id": 1}
        token = service.envelope(report(), 1).report_token
        with patch("career_service.source_text") as source, patch("career_agent.run") as run:
            response = self.client.post("/career/advance", json={"report_token": token + "tampered"})
        self.assertEqual(response.status_code, 409)
        source.assert_not_called()
        run.assert_not_called()

    def test_source_changes_stop_advance_before_any_tool_call(self):
        main.app.dependency_overrides[main.get_current_user] = lambda: {"id": 1}
        with patch("career_service.source_text", return_value=(RESUME + "修改", JD)), patch("career_agent.run") as run:
            response = self.client.post("/career/advance", json={"report_token": service.envelope(report(), 1).report_token})
        self.assertEqual(response.status_code, 409)
        run.assert_not_called()
        self.snapshot.assert_not_called()

    def test_waiting_state_is_saved_and_resumable_without_mutating_facts(self):
        main.app.dependency_overrides[main.get_current_user] = lambda: {"id": 1}
        original = report()
        with patch("career_service.source_text", return_value=(RESUME, JD)):
            response = self.client.post("/career/advance", json={"report_token": service.envelope(original, 1).report_token})
            result = response.json()
            restored, _, _ = service.restore(result["report_token"], 1)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(result["history_saved"])
        self.assertEqual(result["history_id"], 101)
        self.snapshot.assert_called_once()
        self.assertEqual(restored.agent.next_action, "clarify")
        self.assertEqual(restored.requirements, original.requirements)


if __name__ == "__main__":
    unittest.main()
