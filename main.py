import redis
import logging
from uuid import UUID, uuid4
from repositories import get_resume, get_job_description, save_optimization_result, RecordNotFound
from task_store import save_summary, get_summary
from schemas import AgentByIdRequest, AgentRunResponse
from resume_agent import run_resume_agent_by_id
from fastapi.responses import JSONResponse
from database import get_db_connection
from fastapi import (
    FastAPI,
    Depends,
    HTTPException
)

from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials
)

from resume_agent import run_resume_agent
from resume_optimizer import analyze_resume_jd, UnsafeOptimization

from auth_service import (
    register_user,
    login_user,
    get_user_from_token
)

from schemas import (
    RagRequest,
    RagResponse,
    ResumeOptimizeRequest,
    ResumeOptimizeResponse,
    TaskRequest,
    ResumeAgentRequest,
    ResumeAgentResponse,
    RegisterRequest,
    RegisterResponse,
    LoginRequest,
    LoginResponse,
    ResumeCreateRequest,
    ResumeCreateResponse,
    JobDescriptionCreateRequest,
    JobDescriptionCreateResponse,
    ResumeOptimizeByIdRequest,
)


# =========================
# FastAPI App
# =========================

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

app = FastAPI(
    title="AI Career Assistant API",
    version="1.0.0"
)


# =========================
# JWT Security
# =========================

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials

    user = get_user_from_token(
        token
    )

    if "error" in user:
        raise HTTPException(
            status_code=401,
            detail=user["error"]
        )

    return user


# =========================
# Redis Client
# 暂时放这里
# =========================

# =========================
# Health Check
# =========================

@app.get("/")
def home():
    return {
        "message": "AI Career Assistant API is running"
    }


# =========================
# 注册
# =========================

@app.post(
    "/auth/register",
    response_model=RegisterResponse
)
def register(
    request: RegisterRequest
):
    result = register_user(
        name=request.name,
        email=request.email,
        password=request.password
    )

    if "error" in result:
        raise HTTPException(
            status_code=400,
            detail=result["error"]
        )

    return result


# =========================
# 登录
# =========================

@app.post(
    "/auth/login",
    response_model=LoginResponse
)
def login(
    request: LoginRequest
):
    result = login_user(
        email=request.email,
        password=request.password
    )

    if "error" in result:
        raise HTTPException(
            status_code=401,
            detail=result["error"]
        )

    return result


# =========================
# 当前登录用户
# =========================

@app.get("/auth/me")
def auth_me(
    current_user=Depends(get_current_user)
):
    return current_user


# =========================
# Resume + JD Optimizer
# =========================

@app.post(
    "/resume/optimize",
    response_model=ResumeOptimizeResponse
)
def optimize_resume(
    request: ResumeOptimizeRequest
):
    return analyze_resume_jd(
        request.resume,
        request.job_description
    )


# =========================
# Resume Agent
# =========================

@app.post(
    "/resume/agent",
    response_model=ResumeAgentResponse
)
def resume_agent(
    request: ResumeAgentRequest
):
    return run_resume_agent(
        resume=request.resume,
        job_description=request.job_description,
        instruction=request.instruction
    )


# =========================
# RAG
# =========================

@app.post(
    "/rag",
    response_model=RagResponse
)
def rag(
    request: RagRequest
):
    from rag_chroma import rag_answer

    return rag_answer(
        request.question
    )

# =========================
# Redis Task State
# =========================

@app.post("/task/start")
def start_task(request: TaskRequest, current_user=Depends(get_current_user)):
    # Compatibility endpoint: creates an idle summary, not a background job.
    if request.user_id != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="不能为其他用户创建任务")
    task_id = str(uuid4())
    save_summary(current_user["id"], {"task_id": task_id, "status": "idle", "step_count": 0})
    return {"user_id": request.user_id, "task_id": task_id, "status": "idle"}


@app.get("/tasks/{task_id}")
def task_status(task_id: UUID, current_user=Depends(get_current_user)):
    try:
        result = get_summary(current_user["id"], str(task_id))
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="任务状态服务暂不可用") from None
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return result


@app.post("/resume/agent-by-id", response_model=AgentRunResponse)
def agent_by_id(request: AgentByIdRequest, current_user=Depends(get_current_user)):
    result = run_resume_agent_by_id(request, current_user["id"])
    if result["status"] == "error":
        code = result["errors"][-1]["code"]
        status = 404 if code == "not_found" else 504 if code == "timeout" else 502
        return JSONResponse(status_code=status, content=result)
    return result


@app.post(
    "/resumes",
    response_model=ResumeCreateResponse
)
def create_resume(
    request: ResumeCreateRequest,
    current_user=Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO resumes (
                user_id,
                resume_text
            )
            VALUES (%s, %s)
            """,
            (
                current_user["id"],
                request.resume_text
            )
        )

        connection.commit()

        resume_id = cursor.lastrowid

        return {
            "id": resume_id,
            "user_id": current_user["id"],
            "resume_text": request.resume_text,
            "message": "简历保存成功"
        }

    finally:
        cursor.close()
        connection.close()

@app.post(
    "/job-descriptions",
    response_model=JobDescriptionCreateResponse
)
def create_job_description(
    request: JobDescriptionCreateRequest,
    current_user=Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO job_descriptions (
                user_id,
                job_title,
                company,
                jd_text
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                current_user["id"],
                request.job_title,
                request.company,
                request.jd_text
            )
        )

        connection.commit()

        jd_id = cursor.lastrowid

        return {
            "id": jd_id,
            "user_id": current_user["id"],
            "job_title": request.job_title,
            "company": request.company,
            "jd_text": request.jd_text,
            "message": "岗位 JD 保存成功"
        }

    finally:
        cursor.close()
        connection.close()

@app.post(
    "/resume/optimize-by-id",
    response_model=ResumeOptimizeResponse
)
def optimize_resume_by_id(
    request: ResumeOptimizeByIdRequest,
    current_user=Depends(get_current_user)
):
    try:
        resume = get_resume(current_user["id"], request.resume_id)
        jd = get_job_description(current_user["id"], request.job_description_id)
        result = analyze_resume_jd(resume["resume_text"], jd["jd_text"])
        save_optimization_result(current_user["id"], resume["id"], jd["id"], result)
        return result
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    # Do not expose driver/provider errors or request bodies to clients/logs.
    logging.getLogger(__name__).error("request_failed type=%s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "服务暂不可用，请稍后重试"})


@app.exception_handler(UnsafeOptimization)
async def optimization_validation_error(request, exc):
    from resume_optimizer import NoEffectiveOptimization
    code = "no_effective_optimization" if isinstance(exc, NoEffectiveOptimization) else "invalid_optimization"
    return JSONResponse(status_code=502, content={"detail": {
        "code": code, "message": "优化结果未产生有效改写或未通过一致性检查，未保存优化记录"
    }})


from career_api import create_router
app.include_router(create_router(get_current_user))
