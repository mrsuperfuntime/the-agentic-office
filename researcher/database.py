import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "researcher_scheduler.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schedules (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                query         TEXT NOT NULL,
                mode          TEXT NOT NULL DEFAULT 'research',
                schedule_type TEXT NOT NULL,
                schedule_time TEXT,
                schedule_days TEXT,
                interval_hours INTEGER,
                active        INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL,
                last_run      TEXT,
                next_run      TEXT
            );

            CREATE TABLE IF NOT EXISTS reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id   INTEGER,
                schedule_name TEXT NOT NULL,
                query         TEXT NOT NULL,
                mode          TEXT NOT NULL,
                result        TEXT NOT NULL,
                status        TEXT NOT NULL,
                error         TEXT,
                created_at    TEXT NOT NULL
            );
        """)


def _now():
    return datetime.now(timezone.utc).isoformat()


# ── Schedules ──────────────────────────────────────────────────────────────────

def create_schedule(name, query, mode, schedule_type,
                    schedule_time=None, schedule_days=None, interval_hours=None):
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO schedules
               (name, query, mode, schedule_type, schedule_time,
                schedule_days, interval_hours, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (name, query, mode, schedule_type, schedule_time,
             json.dumps(schedule_days) if schedule_days else None,
             interval_hours, _now()),
        )
        return cur.lastrowid


def get_schedules():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_schedule(schedule_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        return dict(row) if row else None


def set_schedule_active(schedule_id, active: bool):
    with _conn() as conn:
        conn.execute(
            "UPDATE schedules SET active = ? WHERE id = ?",
            (int(active), schedule_id),
        )


def update_schedule_run(schedule_id, next_run_iso=None):
    with _conn() as conn:
        conn.execute(
            "UPDATE schedules SET last_run = ?, next_run = ? WHERE id = ?",
            (_now(), next_run_iso, schedule_id),
        )


def delete_schedule(schedule_id):
    with _conn() as conn:
        conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))


# ── Reports ────────────────────────────────────────────────────────────────────

def save_report(schedule_id, schedule_name, query, mode, result, status, error=None):
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO reports
               (schedule_id, schedule_name, query, mode, result, status, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (schedule_id, schedule_name, query, mode,
             json.dumps(result), status, error, _now()),
        )
        return cur.lastrowid


def get_reports(limit=100):
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, schedule_id, schedule_name, query, mode,
                      status, error, created_at
               FROM reports ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_report(report_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not row:
            return None
        r = dict(row)
        try:
            r["result"] = json.loads(r["result"])
        except Exception:
            pass
        return r


def delete_report(report_id):
    with _conn() as conn:
        conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
