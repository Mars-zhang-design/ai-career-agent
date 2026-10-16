"""Contracts for evidence-based career review and human-confirmed updates."""
from typing import Literal
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


class LearningTask(BaseModel):
    requirement_id: str
    objective: str = Field(min_length=1, max_length=800)
    actions: list[str] = Field(min_length=1, max_length=5)
    deliverable: str = Field(min_length=1, max_length=1000)
    acceptance: list[str] = Field(min_length=1, max_length=5)


class LearningDraft(BaseModel):
    tasks: list[LearningTask] = Field(default_factory=list, max_length=20)


class CareerReport(BaseModel):
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


class CareerEnvelope(BaseModel):
    report: CareerReport
    report_token: str


class ReviewRequest(BaseModel):
    resume_id: int = Field(gt=0)
    job_description_id: int = Field(gt=0)


class ReportRequest(BaseModel):
    report_token: str = Field(min_length=1, max_length=250000)


class ChatRequest(ReportRequest):
    message: str = Field(min_length=1, max_length=4000)


class ConfirmRequest(ReportRequest):
    proposal_index: int = Field(ge=0)
    accept: bool


class TargetResponse(BaseModel):
    text: str
    is_target: Literal[True] = True
    pending_count: int
