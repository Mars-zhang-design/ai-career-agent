"""Contracts for evidence-based career review and human-confirmed updates."""
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict

Status = Literal["supported", "partial", "unknown", "gap"]


class RequirementDraft(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    category: Literal["skill", "experience", "qualification", "language"]
    importance: Literal["required", "preferred", "example"]
    jd_quote: str = Field(min_length=1, max_length=1200)
    status: Status
    resume_quotes: list[str] = Field(default_factory=list, max_length=4)
    explanation: str = Field(min_length=1, max_length=1000)
    question: str = Field(default="", max_length=500)


class RequirementsDraft(BaseModel):
    requirements: list[RequirementDraft] = Field(min_length=1, max_length=20)


class Requirement(RequirementDraft):
    id: str
    weight: int
    points: float
    source: Literal["resume", "unconfirmed", "user_confirmed"] = "unconfirmed"
    user_statement: str = ""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class Proposal(BaseModel):
    requirement_id: str
    status: Status
    statement: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=800)


class CoachReply(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
    proposals: list[Proposal] = Field(default_factory=list, max_length=5)


class LearningReference(BaseModel):
    id: str
    title: str = Field(max_length=120)
    source_url: str = Field(max_length=500)
    excerpt: str = Field(max_length=600)
    source: str = Field(max_length=240)
    updated_at: str = Field(default="", max_length=10)


class LearningTaskDraft(BaseModel):
    requirement_id: str
    objective: str = Field(min_length=1, max_length=800)
    actions: list[str] = Field(min_length=1, max_length=5)
    deliverable: str = Field(min_length=1, max_length=1000)
    acceptance: list[str] = Field(min_length=1, max_length=5)
    source_ids: list[str] = Field(default_factory=list, max_length=2)


class LearningTask(LearningTaskDraft):
    references: list[LearningReference] = Field(default_factory=list, max_length=2)
    reference_status: Literal["cited", "uncited", "empty", "unavailable"] = "uncited"
    basis: str = Field(default="", max_length=64)


class LearningDraft(BaseModel):
    tasks: list[LearningTaskDraft] = Field(default_factory=list, max_length=20)


class AgentEvidence(BaseModel):
    requirement_id: str
    basis: str = Field(max_length=64)
    references: list[LearningReference] = Field(default_factory=list, max_length=2)
    state: Literal["available", "empty", "unavailable"]


class AgentStep(BaseModel):
    action: Literal["route", "clarify", "retrieve", "plan", "finish"]
    outcome: Literal["complete", "failed", "fallback"] = "complete"
    requirement_ids: list[str] = Field(default_factory=list, max_length=20)


class CareerAgentState(BaseModel):
    enabled: bool = False
    status: Literal["idle", "waiting", "complete", "failed"] = "idle"
    next_action: Literal["clarify", "confirm", "plan", "done"] = "done"
    note: str = Field(default="", max_length=500)
    clarification_rounds: int = Field(default=0, ge=0, le=1)
    focus_ids: list[str] = Field(default_factory=list, max_length=2)
    plan_ids: list[str] = Field(default_factory=list, max_length=20)
    evidence: list[AgentEvidence] = Field(default_factory=list, max_length=20)
    trace: list[AgentStep] = Field(default_factory=list, max_length=20)


class CareerReport(BaseModel):
    workspace_id: str = Field(default_factory=lambda: str(uuid4()))
    resume_id: int
    job_description_id: int
    source_hash: str
    requirements: list[Requirement]
    score: int = Field(ge=0, le=100)
    evidence_coverage: int = Field(ge=0, le=100)
    warnings: list[str] = Field(default_factory=list)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=12)
    pending: list[Proposal] = Field(default_factory=list)
    tasks: list[LearningTask] = Field(default_factory=list)
    revision: int = 1
    agent: CareerAgentState = Field(default_factory=CareerAgentState)


class CareerEnvelope(BaseModel):
    report: CareerReport
    report_token: str
    history_saved: bool = False
    history_id: int | None = None
    persistence_warning: str = ""


class ReviewRequest(BaseModel):
    resume_id: int = Field(gt=0)
    job_description_id: int = Field(gt=0)


class ReportRequest(BaseModel):
    report_token: str = Field(min_length=1, max_length=250000)


class AdvanceRequest(ReportRequest):
    skip_clarification: bool = False


class ChatRequest(ReportRequest):
    message: str = Field(min_length=1, max_length=4000)


class ConfirmRequest(ReportRequest):
    proposal_index: int = Field(ge=0)
    accept: bool


class TargetItem(BaseModel):
    requirement_id: str
    title: str
    status: Literal["confirm", "complete"]
    status_label: str
    jd_quote: str
    next_step: str
    objective: str = ""
    deliverable: str = ""
    acceptance: list[str] = Field(default_factory=list)
    question: str = ""


class TargetResponse(BaseModel):
    text: str
    is_target: Literal[True] = True
    pending_count: int
    current_resume: str = ""
    confirmed_additions: list[str] = Field(default_factory=list)
    items: list[TargetItem] = Field(default_factory=list)
