"""Small, owner-scoped SQL operations. Never hold a connection during an LLM call."""
from contextlib import contextmanager
from database import get_db_connection


class RecordNotFound(Exception):
    pass


@contextmanager
def transaction():
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        yield connection, cursor
    except Exception:
        connection.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def get_resume(user_id, resume_id):
    with transaction() as (_, cursor):
        cursor.execute("SELECT id, resume_text FROM resumes WHERE id=%s AND user_id=%s",
                       (resume_id, user_id))
        row = cursor.fetchone()
        if row is None:
            raise RecordNotFound("没有找到该简历")
        return row


def get_job_description(user_id, job_description_id):
    with transaction() as (_, cursor):
        cursor.execute("SELECT id, jd_text FROM job_descriptions WHERE id=%s AND user_id=%s",
                       (job_description_id, user_id))
        row = cursor.fetchone()
        if row is None:
            raise RecordNotFound("没有找到该岗位 JD")
        return row


def save_optimization_result(user_id, resume_id, job_description_id, result):
    # Recheck ownership at the write boundary. This write is intentionally NOT retried:
    # a lost commit acknowledgement can mean the row already exists.
    with transaction() as (connection, cursor):
        for table, record_id in (("resumes", resume_id), ("job_descriptions", job_description_id)):
            cursor.execute(f"SELECT id FROM {table} WHERE id=%s AND user_id=%s FOR UPDATE",
                           (record_id, user_id))
            if cursor.fetchone() is None:
                raise RecordNotFound("记录不存在或无权访问")
        cursor.execute(
            "INSERT INTO optimization_records "
            "(user_id, resume_id, job_description_id, match_score, optimized_resume) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, resume_id, job_description_id, result["match_score"], result["optimized_resume"]),
        )
        record_id = cursor.lastrowid
        connection.commit()
        return record_id


def create_resume_text(user_id, text):
    with transaction() as (connection, cursor):
        cursor.execute("INSERT INTO resumes (user_id, resume_text) VALUES (%s, %s)", (user_id, text))
        record_id = cursor.lastrowid
        connection.commit()
        return record_id
