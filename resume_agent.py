"""Public Agent entry points; legacy text requests share the same graph."""
import time
from uuid import uuid4
from langgraph.errors import GraphRecursionError
from agent_graph import build_graph
from agent_tools import BusinessTools, ToolContext
from schemas import AgentByIdRequest, AgentRunResponse
from task_store import save_summary


def run_agent(request, user_id=None, resume=None, job_description=None):
    persist = user_id is not None
    state = {
        **request, "task_id": str(uuid4()), "status": "running", "step_count": 0,
        "repair_count": 0, "deadline": time.monotonic() + 120,
        "errors": [], "warnings": [], "trace": [], "knowledge": [],
        "knowledge_attempted": False,
    }
    if resume is not None:
        state.update(resume=resume, job_description=job_description)
    tools = BusinessTools(ToolContext(user_id=user_id, persist=persist))
    latest = state
    def observe(value):
        nonlocal latest
        latest = value
        save_summary(user_id, value)
    observe(state)
    try:
        final = build_graph(tools, observer=observe).invoke(state, {"recursion_limit": 32})
    except GraphRecursionError:
        final = {**latest, "status": "error", "errors": latest["errors"] + [
            {"code": "recursion_limit", "tool": "agent", "message": "执行已达到图步数上限"}]}
    save_summary(user_id, final)
    success = final["status"] == "success"
    response = AgentRunResponse(
        task_id=final["task_id"], status="success" if success else "error",
        message="任务完成" if success else "任务未完成，请查看 errors",
        analysis=final.get("analysis_result"), optimization=final.get("optimization_result"),
        record_id=final.get("record_id"), saved=bool(final.get("record_id")),
        warnings=final["warnings"], errors=final["errors"], steps=final["step_count"],
    )
    return response.model_dump()


def run_resume_agent_by_id(request: AgentByIdRequest, user_id: int):
    return run_agent(request.model_dump(), user_id=user_id)


def run_resume_agent(resume: str, job_description: str, instruction: str):
    if not resume.strip() or not job_description.strip():
        return {"status": "error", "message": "简历和 JD 不能为空", "result": None}
    result = run_agent({"instruction": instruction, "mode": "optimize", "match_threshold": 60,
                        "use_knowledge": True}, resume=resume, job_description=job_description)
    return {"status": result["status"], "message": result["message"],
            "result": result["optimization"] if result["status"] == "success" else None}
