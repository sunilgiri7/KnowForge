from __future__ import annotations

import logging

from app.core.config import settings
from app.db.models import User, WorkspaceMember
from app.db.session import SessionLocal
from app.llmwiki.storage import WikiStore
from app.services.tier4 import DailyDigestService

logger = logging.getLogger("knowforge.tier4")
_scheduler = None


def _run_daily_digest_job() -> None:
    db = SessionLocal()
    try:
        memberships = db.query(WorkspaceMember).all()
        seen: set[tuple[str, str]] = set()
        for membership in memberships:
            key = (membership.workspace_id, membership.user_id)
            if key in seen:
                continue
            seen.add(key)
            user = db.get(User, membership.user_id)
            workspace = membership.workspace
            if not user or not workspace:
                continue
            store = WikiStore().for_workspace(workspace.id)
            DailyDigestService(db, store).generate_for_user(workspace=workspace, user=user, send_email=settings.tier4_digest_email_enabled)
    except Exception:
        logger.exception("Tier 4 daily digest job failed")
    finally:
        db.close()


def start_tier4_scheduler() -> None:
    global _scheduler
    if not settings.tier4_digest_enabled or _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception:
        logger.warning("APScheduler is not installed; Tier 4 digest scheduler is disabled.")
        return
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _run_daily_digest_job,
        CronTrigger(hour=max(0, min(23, settings.tier4_digest_hour_utc)), minute=0),
        id="tier4_daily_digest",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Tier 4 daily digest scheduler started")


def stop_tier4_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
