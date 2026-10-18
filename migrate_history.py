"""Explicit additive migration: never run schema changes at app startup."""
from pathlib import Path
from database import get_db_connection

if __name__ == '__main__':
    connection = get_db_connection()
    try:
        cursor = connection.cursor()
        cursor.execute((Path(__file__).parent / 'migrations/001_career_snapshots.sql').read_text(encoding='utf-8-sig'))
        connection.commit()
        cursor.close()
        print('career_snapshots table ready; existing tables unchanged')
    finally:
        connection.close()
