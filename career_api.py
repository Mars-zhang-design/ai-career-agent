"""Authenticated career endpoints; reuse existing tables and ownership checks."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from career_models import (ReviewRequest, ReportRequest, AdvanceRequest, ChatRequest, ConfirmRequest, CareerEnvelope, TargetResponse)
from repositories import RecordNotFound
import career_service as service
from history_repository import save_snapshot
from resume_optimizer import UnsafeOptimization, NoEffectiveOptimization


def create_router(current_user):
    router = APIRouter(prefix="/career", tags=["职业成长"])

    def call(action, *args):
        try:
            result = action(*args)
            if isinstance(result, CareerEnvelope):
                try:
                    result.history_id = save_snapshot(args[0], result.report, action.__name__)
                    result.history_saved = True
                except Exception as exc:
                    logging.getLogger(__name__).warning("progress_save_failed type=%s", type(exc).__name__)
                    result.persistence_warning = "本次结果已生成，但未确认保存到历史。请保留页面，并点击保存当前进度重试。"
            return result
        except RecordNotFound:
            raise HTTPException(404, "资料不存在或无权访问") from None
        except service.ReportError as exc:
            raise HTTPException(409, str(exc)) from None
        except UnsafeOptimization as exc:
            code = "no_effective_optimization" if isinstance(exc, NoEffectiveOptimization) else "invalid_optimization"
            # Only controlled validation messages, never raw provider text or resume excerpts.
            reason = "；".join(exc.reasons) if exc.reasons else str(exc)
            raise HTTPException(502, {"code": code, "message": "简历美化未通过检查，未保存：" + reason}) from None
        except Exception as exc:
            logging.getLogger(__name__).warning("career_failed type=%s", type(exc).__name__)
            raise HTTPException(502, "本次处理未完成，请稍后再试；没有自动修改简历。") from None

    @router.post("/review", response_model=CareerEnvelope)
    def review(request: ReviewRequest, user=Depends(current_user)):
        return call(service.review, user["id"], request.resume_id, request.job_description_id)

    @router.post("/chat", response_model=CareerEnvelope)
    def chat(request: ChatRequest, user=Depends(current_user)):
        return call(service.chat, user["id"], request.report_token, request.message)

    @router.post("/confirm", response_model=CareerEnvelope)
    def confirm(request: ConfirmRequest, user=Depends(current_user)):
        return call(service.confirm, user["id"], request.report_token, request.proposal_index, request.accept)

    @router.post("/plan", response_model=CareerEnvelope)
    def plan(request: ReportRequest, user=Depends(current_user)):
        return call(service.make_plan, user["id"], request.report_token)

    @router.post("/advance", response_model=CareerEnvelope)
    def advance(request: AdvanceRequest, user=Depends(current_user)):
        return call(service.advance, user["id"], request.report_token, request.skip_clarification)

    @router.post("/target", response_model=TargetResponse)
    def target(request: ReportRequest, user=Depends(current_user)):
        return call(service.target_resume, user["id"], request.report_token)

    @router.post("/resume")
    def promote(request: ReportRequest, user=Depends(current_user)):
        return call(service.promote, user["id"], request.report_token)

    @router.post("/polish")
    def polish(request: ReportRequest, user=Depends(current_user)):
        return call(service.polish, user["id"], request.report_token)

    return router
