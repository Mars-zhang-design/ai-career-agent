"""Tools receive server-owned identity and validated state, never arbitrary SQL."""
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field
import repositories
import resume_optimizer as optimizer
from schemas import MatchAnalysis, ResumeOptimizeResponse


class RetrievalArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000)


@dataclass(frozen=True)
class ToolContext:
    user_id: int | None
    persist: bool = True


class BusinessTools:
    def __init__(self, context: ToolContext):
        self.context = context

    def execute(self, name, state, arguments):
        if name != "retrieve_job_knowledge" and arguments:
            raise ValueError("该工具不接受模型提供的参数")
        handler = getattr(self, name, None) if name in TOOL_NAMES else None
        if handler is None:
            raise ValueError("未知工具")
        return handler(state, arguments)

    def get_resume(self, state, arguments):
        row = repositories.get_resume(self.context.user_id, state["resume_id"])
        return {"resume": row["resume_text"]}

    def get_job_description(self, state, arguments):
        row = repositories.get_job_description(self.context.user_id, state["job_description_id"])
        return {"job_description": row["jd_text"]}

    def analyze_match(self, state, arguments):
        result = optimizer.analyze_match(state["resume"], state["job_description"],
                                        state.get("knowledge"), state["deadline"])
        return {"analysis_result": MatchAnalysis.model_validate(result).model_dump()}

    def retrieve_job_knowledge(self, state, arguments):
        from rag_chroma import retrieve
        args = RetrievalArguments.model_validate(arguments)
        return {"knowledge": retrieve(args.query), "knowledge_attempted": True}

    def optimize_resume(self, state, arguments):
        result = optimizer.optimize_resume(
            state["resume"], state["job_description"], state["analysis_result"],
            state.get("knowledge"), state.get("warnings"), state["deadline"],
            instruction=state.get("instruction", ""),
        )
        result = ResumeOptimizeResponse.model_validate(result).model_dump()
        problems = optimizer.validate_resume_result(state["resume"], result)
        if problems:
            if state.get("repair_count", 0) >= 1:
                optimizer.reject_optimization(state["resume"], result)
            return {"repair_count": 1, "warnings": state.get("warnings", []) + problems}
        return {"optimization_result": result}

    def save_optimization_result(self, state, arguments):
        if not self.context.persist or self.context.user_id is None:
            raise ValueError("当前任务不能保存")
        if state.get("record_id"):
            return {"record_id": state["record_id"]}
        result = ResumeOptimizeResponse.model_validate(state["optimization_result"]).model_dump()
        if optimizer.validate_resume_result(state["resume"], result):
            optimizer.reject_optimization(state["resume"], result)
        record_id = repositories.save_optimization_result(
            self.context.user_id, state["resume_id"], state["job_description_id"], result,
        )
        return {"record_id": record_id}


TOOL_NAMES = (
    "get_resume", "get_job_description", "analyze_match",
    "retrieve_job_knowledge", "optimize_resume", "save_optimization_result",
)
