"""Serializable per-run state; identity lives in server-owned tool context."""
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
    resume_id: int
    job_description_id: int
    instruction: str
    mode: str
    match_threshold: int
    use_knowledge: bool
    resume: str
    job_description: str
    knowledge: list[dict]
    knowledge_attempted: bool
    analysis_result: dict
    optimization_result: dict
    record_id: int
    next_action: str
    next_arguments: dict
    step_count: int
    repair_count: int
    deadline: float
    status: str
    warnings: list[str]
    errors: list[dict]
    trace: list[dict[str, Any]]
