from pydantic import BaseModel, Field
from typing import List, Literal
from career_models import Requirement


class RagRequest(BaseModel):
    question: str


class SourceMetadata(BaseModel):
    chunk_id: int
    source: str
    title: str = ""
    source_url: str = ""
    category: str = ""
    updated_at: str = ""


class RagSource(BaseModel):
    content: str
    metadata: SourceMetadata
    distance: float


class RagResponse(BaseModel):
    answer: str
    sources: List[RagSource]


class ResumeOptimizeRequest(BaseModel):
    resume: str
    job_description: str


class RewriteSuggestion(BaseModel):
    original: str
    optimized: str
    segment_id: int | None = None
    issue: str = ""
    reason: str = ""
    evidence: List[str] = Field(default_factory=list)
    jd_evidence: str = ""


class ResumeOptimizeResponse(BaseModel):
    match_score: int = Field(ge=0, le=100)
    matched_skills: List[str]
    missing_skills: List[str]
    jd_keywords: List[str]
    rewrite_suggestions: List[RewriteSuggestion]
    warnings: List[str]
    optimized_resume: str

class ResumeAgentRequest(BaseModel):
    resume: str
    job_description: str
    instruction: str


class ResumeAgentResponse(BaseModel):
    status: str
    message: str
    result: dict | None = None

class TaskRequest(BaseModel):
    user_id: str

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class RegisterResponse(BaseModel):
    id: int
    name: str
    email: str
    message: str

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    name: str
    email: str


class ResumeCreateRequest(BaseModel):
    resume_text: str


class ResumeCreateResponse(BaseModel):
    id: int
    user_id: int
    resume_text: str
    message: str

class JobDescriptionCreateRequest(BaseModel):
    job_title: str
    company: str
    jd_text: str


class JobDescriptionCreateResponse(BaseModel):
    id: int
    user_id: int
    job_title: str
    company: str
    jd_text: str
    message: str

class ResumeOptimizeByIdRequest(BaseModel):
    resume_id: int
    job_description_id: int

class MatchAnalysis(BaseModel):
    match_score: int = Field(ge=0, le=100)
    matched_skills: List[str]
    missing_skills: List[str]
    jd_keywords: List[str]
    warnings: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    requirements: List[Requirement] = Field(default_factory=list)
    evidence_coverage: int = Field(default=0, ge=0, le=100)


class AgentByIdRequest(BaseModel):
    resume_id: int = Field(gt=0)
    job_description_id: int = Field(gt=0)
    instruction: str = Field(default="分析匹配情况并优化简历", max_length=4000)
    mode: Literal["analyze", "optimize", "conditional"] = "optimize"
    match_threshold: int = Field(default=60, ge=0, le=100)
    use_knowledge: bool = True


class AgentError(BaseModel):
    code: str
    tool: str
    message: str


class AgentRunResponse(BaseModel):
    task_id: str
    status: Literal["success", "error"]
    message: str
    analysis: MatchAnalysis | None = None
    optimization: ResumeOptimizeResponse | None = None
    record_id: int | None = None
    saved: bool = False
    warnings: List[str] = Field(default_factory=list)
    errors: List[AgentError] = Field(default_factory=list)
    steps: int = 0


class SegmentEdit(BaseModel):
    segment_id: int = Field(ge=1)
    optimized: str = Field(min_length=1)
    issue: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: List[str] = Field(min_length=1)
    jd_evidence: str = Field(min_length=1)


class SegmentRewritePlan(BaseModel):
    edits: List[SegmentEdit] = Field(default_factory=list, max_length=6)
    warnings: List[str] = Field(default_factory=list)


class GeneralSegmentEdit(SegmentEdit):
    jd_evidence: str = ""


class GeneralRewritePlan(BaseModel):
    edits: List[GeneralSegmentEdit] = Field(default_factory=list, max_length=6)
    warnings: List[str] = Field(default_factory=list)
