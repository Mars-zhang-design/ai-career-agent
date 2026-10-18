"""Owner-scoped history. Immutable report snapshots; JWTs are never persisted."""
import hashlib
import json
from repositories import transaction, RecordNotFound

KINDS = {'resumes', 'jobs', 'optimizations', 'sessions'}


def save_snapshot(user_id, report, action):
    payload = report.model_dump_json()
    checksum = hashlib.sha256(payload.encode()).hexdigest()
    with transaction() as (connection, cursor):
        cursor.execute('INSERT INTO career_snapshots '
            '(user_id,workspace_id,resume_id,job_description_id,action,payload_hash,report_json) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)',
            (user_id, report.workspace_id, report.resume_id, report.job_description_id, action, checksum, payload))
        identity = cursor.lastrowid
        connection.commit()
        return identity


def list_records(user_id, kind, before=0, limit=20):
    if kind not in KINDS:
        raise ValueError('未知历史分类')
    limit = min(max(limit, 1), 50)
    queries = {
        'resumes': 'SELECT id, created_at, LEFT(resume_text,80) AS title FROM resumes WHERE user_id=%s',
        'jobs': 'SELECT id, created_at, job_title AS title, company FROM job_descriptions WHERE user_id=%s',
        'optimizations': 'SELECT id, created_at, resume_id, job_description_id, match_score FROM optimization_records WHERE user_id=%s',
        'sessions': 'SELECT id, created_at, resume_id, job_description_id, action FROM career_snapshots '
                    'WHERE user_id=%s AND id IN (SELECT MAX(id) FROM career_snapshots WHERE user_id=%s GROUP BY workspace_id)',
    }
    args = [user_id, user_id] if kind == 'sessions' else [user_id]
    sql = queries[kind]
    if before:
        sql += ' AND id < %s'
        args.append(before)
    args.append(min(max(limit, 1), 50) + 1)
    with transaction() as (_, cursor):
        cursor.execute(sql + ' ORDER BY id DESC LIMIT %s', tuple(args))
        rows = cursor.fetchall()
    page = rows[:limit]
    return {'items': page, 'next_before': page[-1]['id'] if len(rows) > limit and page else None}


def get_record(user_id, kind, identity):
    tables = {'resumes': 'resumes', 'jobs': 'job_descriptions',
              'optimizations': 'optimization_records', 'sessions': 'career_snapshots'}
    fields = {'resumes': 'id,resume_text,created_at', 'jobs': 'id,job_title,company,jd_text,created_at',
              'optimizations': 'id,resume_id,job_description_id,match_score,optimized_resume,created_at',
              'sessions': 'id,report_json,created_at,action'}
    if kind not in tables:
        raise ValueError('未知历史分类')
    with transaction() as (_, cursor):
        cursor.execute(f'SELECT {fields[kind]} FROM {tables[kind]} WHERE id=%s AND user_id=%s', (identity,user_id))
        row = cursor.fetchone()
    if row is None:
        raise RecordNotFound('记录不存在或无权访问')
    return row
