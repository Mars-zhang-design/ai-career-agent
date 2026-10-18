"""HTTP workflow; the server chooses the next action and preserves partial work."""
from web_client import ApiError


def has_plan_candidates(report):
    return any(row['category'] in ('skill', 'experience') and row['status'] != 'supported'
               and row['importance'] != 'example' for row in report['requirements'])


def _remember(state, value, context):
    state['career'] = value
    state['career_context'] = context
    for key in ('target_resume', 'promoted_resume', 'workflow_result'):
        state.pop(key, None)


def run_review(api, state, resume_data, job_data, *, auto_plan=False, on_stage=None):
    stage = on_stage or (lambda message: None)
    context = (resume_data, job_data)
    stage('1 / 3 · 保存本次资料')
    if not state.get('resume_id') or state.get('saved_resume') != resume_data:
        saved = api('POST', '/resumes', resume_data)
        state.update(resume_id=saved['id'], saved_resume=resume_data)
    if not state.get('job_description_id') or state.get('saved_job') != job_data:
        saved = api('POST', '/job-descriptions', job_data)
        state.update(job_description_id=saved['id'], saved_job=job_data)
    stage('2 / 3 · 比对岗位要求与已有经历')
    reviewed = api('POST', '/career/review', {'resume_id': state['resume_id'],
                                             'job_description_id': state['job_description_id']})
    _remember(state, reviewed, context)
    outcome = {'plan_state': 'manual', 'plan_error': ''}
    if auto_plan:
        stage('3 / 3 · 根据当前证据安排下一步')
        try:
            planned = api('POST', '/career/advance', {'report_token': reviewed['report_token']})
        except ApiError as exc:
            if exc.status == 401:
                raise
            outcome.update(plan_state='failed', plan_error=str(exc))
        else:
            _remember(state, planned, context)
            agent = planned['report'].get('agent', {})
            status = agent.get('status')
            if status in ('waiting', 'failed'):
                outcome.update(plan_state=status, plan_error=agent.get('note', '') if status == 'failed' else '')
            elif status == 'complete':
                outcome['plan_state'] = 'complete' if planned['report'].get('tasks') else 'skipped'
            else:
                outcome['plan_state'] = 'complete'  # Compatibility with older mock/client responses.
    elif not has_plan_candidates(reviewed['report']):
        outcome['plan_state'] = 'skipped'
        stage('3 / 3 · 整理目标清单，无需生成技能练习')
    else:
        stage('3 / 3 · 整理目标清单，行动计划可按需生成')
    return outcome
