"""Authenticated library and resumable career progress."""
import logging
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from career_models import CareerReport, ReportRequest
from repositories import RecordNotFound
import career_service as service
import history_repository as history

Kind = Literal['resumes','jobs','optimizations','sessions']


def load_progress(user_id, identity):
    record = history.get_record(user_id, 'sessions', identity)
    report = CareerReport.model_validate_json(record['report_json'])
    resume = history.get_record(user_id, 'resumes', report.resume_id)
    job = history.get_record(user_id, 'jobs', report.job_description_id)
    if report.source_hash != service.fingerprint(resume['resume_text'], job['jd_text']):
        raise service.ReportError('原始资料已变化，请从历史资料重新发起分析。')
    result = service.envelope(report, user_id)
    result.history_saved = True
    result.history_id = identity
    return {'career': result.model_dump(), 'resume': resume, 'job': job}


def create_router(current_user):
    router = APIRouter(prefix='/history', tags=['我的历史'])

    def call(function, *args):
        try:
            return function(*args)
        except RecordNotFound:
            raise HTTPException(404, '记录不存在或无权访问') from None
        except service.ReportError as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception as exc:
            logging.getLogger(__name__).warning('history_failed type=%s', type(exc).__name__)
            raise HTTPException(503, '历史记录暂不可用，请确认数据库连接及历史表已初始化。') from None

    @router.post('/save-progress')
    def save_progress(request: ReportRequest, user=Depends(current_user)):
        def save():
            report, _, _ = service.restore(request.report_token, user['id'])
            identity = history.save_snapshot(user['id'], report, 'manual')
            result = service.envelope(report, user['id'])
            result.history_saved, result.history_id = True, identity
            return {'id': identity, 'saved': True, 'career': result.model_dump()}
        return call(save)

    @router.get('/sessions/{identity}/resume')
    def resume_progress(identity: int, user=Depends(current_user)):
        return call(load_progress, user['id'], identity)

    @router.get('/{kind}')
    def listing(kind: Kind, before: int = Query(0, ge=0), user=Depends(current_user)):
        return call(history.list_records, user['id'], kind, before)

    @router.get('/{kind}/{identity}')
    def detail(kind: Kind, identity: int, user=Depends(current_user)):
        def read():
            row = history.get_record(user['id'], kind, identity)
            if kind == 'sessions':
                row['report'] = CareerReport.model_validate_json(row.pop('report_json')).model_dump()
            return row
        return call(read)

    return router
