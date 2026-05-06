"""
auto_reporter.py
================
Background scheduler that auto-generates and uploads all 3 HTML reports
to Bitrix24 Drive every day at the configured report_time.

How to enable:
  Call start_scheduler(app) once at FastAPI startup in main.py:

    from auto_reporter import start_scheduler

    @app.on_event("startup")
    async def startup():
        start_scheduler(app)

The scheduler reads WorkEye credentials and report_time from the database
(stored when the admin connects WorkEye inside the Bitrix24 app) and runs
the reports every day at exactly that time (IST).

If report_time is not configured it defaults to 23:59 IST.

Dependencies (add to requirements.txt if missing):
  APScheduler>=3.10
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    _HAS_APSCHEDULER = True
except ImportError:
    _HAS_APSCHEDULER = False
    logging.warning("[auto_reporter] APScheduler not installed — scheduler disabled. "
                    "Run: pip install apscheduler")

import database
import workeye_service as ws
import bitrix_service  as bs

log = logging.getLogger("auto_reporter")
IST = timezone(timedelta(hours=5, minutes=30))

_scheduler = None


# ─────────────────────────────────────────────────────────────────────────────
# Core report job
# ─────────────────────────────────────────────────────────────────────────────

async def _run_reports_for_portal(portal: dict):
    """
    Fetch live WorkEye data for one Bitrix portal and upload all reports.
    `portal` must have keys: member_id, workeye_url, workeye_email, workeye_password
    (or a valid workeye_token if you store it).
    """
    member_id = portal.get("member_id", "?")
    workeye_url = portal.get("workeye_url") or portal.get("workeye_base_url")
    email       = portal.get("workeye_email")
    password    = portal.get("workeye_password")
    token       = portal.get("workeye_token")

    if not workeye_url:
        log.warning(f"[auto_reporter] Portal {member_id}: no workeye_url — skipping")
        return

    # Re-authenticate if we only have credentials (no cached token)
    if not token:
        if not email or not password:
            log.warning(f"[auto_reporter] Portal {member_id}: no token or credentials — skipping")
            return
        try:
            auth = ws.get_token(workeye_url, email, password)
            token = auth["token"]
            log.info(f"[auto_reporter] Portal {member_id}: re-authenticated OK")
        except Exception as e:
            log.error(f"[auto_reporter] Portal {member_id}: auth failed — {e}")
            return

    # Fetch stats + attendance
    try:
        stats_response = ws.get_stats(workeye_url, token)
    except Exception as e:
        log.error(f"[auto_reporter] Portal {member_id}: get_stats failed — {e}")
        return

    try:
        attendance = ws.get_attendance(workeye_url, token)
    except Exception as e:
        log.warning(f"[auto_reporter] Portal {member_id}: get_attendance failed — {e} (continuing)")
        attendance = None

    # Generate and upload all reports + CRM comments
    try:
        results = bs.run_all_reports(stats_response, attendance)
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        log.info(
            f"[auto_reporter] Portal {member_id} @ {now_str} IST — "
            f"daily={results.get('daily',{}).get('success')} "
            f"attendance={results.get('attendance',{}).get('success')} "
            f"employee={results.get('employee',{}).get('success')} "
            f"crm={results.get('crm_comments',{})}"
        )
    except Exception as e:
        log.error(f"[auto_reporter] Portal {member_id}: run_all_reports failed — {e}")


async def _daily_report_job():
    """Scheduled job: run reports for every registered portal."""
    log.info("[auto_reporter] Daily report job started")
    try:
        portals = database.get_all_portals()   # returns list of portal dicts
    except Exception as e:
        log.error(f"[auto_reporter] Could not load portals: {e}")
        return

    if not portals:
        log.info("[auto_reporter] No portals registered — nothing to do")
        return

    tasks = [_run_reports_for_portal(p) for p in portals]
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("[auto_reporter] Daily report job finished")


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler setup
# ─────────────────────────────────────────────────────────────────────────────

def _get_report_time() -> tuple[int, int]:
    """
    Read report_time from the first portal's configuration.
    Falls back to 23:59 IST if not set.
    Returns (hour, minute) in IST.
    """
    default_hour, default_minute = 23, 59
    try:
        portals = database.get_all_portals()
        if not portals:
            return default_hour, default_minute
        # Use the first portal's report_time setting
        rt = portals[0].get("report_time") or ""
        if rt and ":" in str(rt):
            parts = str(rt).split(":")
            return int(parts[0]), int(parts[1])
    except Exception as e:
        log.warning(f"[auto_reporter] Could not read report_time: {e}")
    return default_hour, default_minute


def start_scheduler(app=None):
    """
    Call once at FastAPI startup to start the daily report scheduler.
    Pass the FastAPI `app` instance if you want lifespan management.
    """
    global _scheduler

    if not _HAS_APSCHEDULER:
        log.warning("[auto_reporter] APScheduler missing — scheduler not started")
        return

    if _scheduler and _scheduler.running:
        log.info("[auto_reporter] Scheduler already running")
        return

    hour, minute = _get_report_time()
    log.info(f"[auto_reporter] Scheduling daily reports at {hour:02d}:{minute:02d} IST")

    _scheduler = AsyncIOScheduler(timezone=IST)
    _scheduler.add_job(
        _daily_report_job,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=IST),
        id="daily_workeye_report",
        replace_existing=True,
    )
    _scheduler.start()
    log.info("[auto_reporter] Scheduler started ✓")

    # Graceful shutdown when FastAPI stops
    if app is not None:
        @app.on_event("shutdown")
        async def _shutdown_scheduler():
            if _scheduler and _scheduler.running:
                _scheduler.shutdown(wait=False)
                log.info("[auto_reporter] Scheduler shut down")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("[auto_reporter] Scheduler stopped")


def trigger_now():
    """Manually fire the report job immediately (useful for testing)."""
    asyncio.create_task(_daily_report_job())