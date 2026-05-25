import json
import logging
from datetime import timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import database as db

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="UTC")


# ── Job execution ──────────────────────────────────────────────────────────────

def _run_job(schedule_id: int, schedule_name: str, query: str, mode: str):
    logger.info("Scheduled job starting: %s (id=%d)", schedule_name, schedule_id)
    try:
        from research_agent import ResearchAgent

        agent = ResearchAgent()

        if mode == "products":
            result = agent.research_and_rank(query, limit=12)
        elif mode == "quick":
            answer = agent.quick_answer(query)
            result = {"answer": answer}
        else:
            result = agent.run(query)

        db.save_report(schedule_id, schedule_name, query, mode, result, "success")
        logger.info("Scheduled job done: %s", schedule_name)
    except Exception as exc:
        logger.error("Scheduled job failed: %s — %s", schedule_name, exc)
        db.save_report(schedule_id, schedule_name, query, mode, {}, "error", str(exc))
    finally:
        job = _scheduler.get_job(f"sched_{schedule_id}")
        next_run = None
        if job and job.next_run_time:
            next_run = job.next_run_time.astimezone(timezone.utc).isoformat()
        db.update_schedule_run(schedule_id, next_run)


# ── Trigger builder ────────────────────────────────────────────────────────────

def _make_trigger(schedule: dict):
    t = schedule["schedule_type"]
    if t == "daily":
        h, m = schedule["schedule_time"].split(":")
        return CronTrigger(hour=int(h), minute=int(m), timezone="UTC")
    if t == "weekly":
        days = json.loads(schedule["schedule_days"]) if schedule.get("schedule_days") else ["mon"]
        h, m = schedule["schedule_time"].split(":")
        return CronTrigger(
            day_of_week=",".join(days), hour=int(h), minute=int(m), timezone="UTC"
        )
    if t == "interval":
        return IntervalTrigger(hours=int(schedule["interval_hours"]))
    raise ValueError(f"Unknown schedule_type: {t!r}")


# ── Public API ─────────────────────────────────────────────────────────────────

def add_job(schedule: dict):
    try:
        trigger = _make_trigger(schedule)
        job = _scheduler.add_job(
            _run_job,
            trigger=trigger,
            id=f"sched_{schedule['id']}",
            kwargs={
                "schedule_id":   schedule["id"],
                "schedule_name": schedule["name"],
                "query":         schedule["query"],
                "mode":          schedule["mode"],
            },
            replace_existing=True,
            misfire_grace_time=600,
        )
        next_run = job.next_run_time.astimezone(timezone.utc).isoformat() if job.next_run_time else None
        db.update_schedule_run(schedule["id"], next_run)
    except Exception as exc:
        logger.error("Could not add job for schedule %s: %s", schedule.get("name"), exc)


def remove_job(schedule_id: int):
    job_id = f"sched_{schedule_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)


def get_next_run(schedule_id: int):
    job = _scheduler.get_job(f"sched_{schedule_id}")
    if job and job.next_run_time:
        return job.next_run_time.astimezone(timezone.utc).isoformat()
    return None


def startup():
    schedules = db.get_schedules()
    active = [s for s in schedules if s["active"]]
    for s in active:
        try:
            add_job(s)
        except Exception as exc:
            logger.warning("Could not restore job '%s': %s", s["name"], exc)
    _scheduler.start()
    logger.info("Scheduler started — %d active job(s)", len(active))


def shutdown():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
