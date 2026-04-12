"""
APScheduler service — creates a Run and submits it to the executor whenever a
cron-scheduled task fires.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)


def get_scheduler() -> AsyncIOScheduler:
    return _scheduler


async def startup() -> None:
    _scheduler.start()
    # Load existing cron tasks from DB on startup
    await _reload_cron_jobs()
    logger.info("Scheduler started")


async def shutdown() -> None:
    _scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


async def _reload_cron_jobs() -> None:
    from app.db.session import AsyncSessionLocal
    from app.db.models.task import Task
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Task).where(Task.cron_expr.isnot(None)))
        tasks = result.scalars().all()

    for task in tasks:
        schedule_task(task.id, task.cron_expr)


def schedule_task(task_id: str, cron_expr: str) -> None:
    """Add or replace the cron job for a task."""
    job_id = f"task_{task_id}"
    _scheduler.add_job(
        _trigger_task,
        CronTrigger.from_crontab(cron_expr, timezone=settings.scheduler_timezone),
        id=job_id,
        args=[task_id],
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.debug("Scheduled task %s with cron %r", task_id, cron_expr)


def unschedule_task(task_id: str) -> None:
    job_id = f"task_{task_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
        logger.debug("Unscheduled task %s", task_id)


async def _trigger_task(task_id: str) -> None:
    """Called by APScheduler — enqueues a pending Run for the consumer.

    Skips enqueueing if the task already has a pending or running run, so
    overlapping cron fires don't stack up.
    """
    from sqlalchemy import select
    from ulid import ULID
    from app.db.session import AsyncSessionLocal
    from app.db.models.task import Task
    from app.db.models.run import Run
    from app.executor.run_executor import notify_new_run

    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None:
            logger.warning("Scheduled trigger: task %s not found", task_id)
            return

        existing = await db.execute(
            select(Run.id)
            .where(Run.task_id == task_id, Run.status.in_(("pending", "running")))
            .limit(1)
        )
        if existing.scalar_one_or_none():
            logger.info(
                "Scheduler skipping task %s — a pending/running run already exists", task_id
            )
            return

        run_id = str(ULID())
        db.add(Run(
            id=run_id,
            task_id=task_id,
            agent_id=task.agent_id,
            status="pending",
            priority=task.default_priority or 0,
        ))
        await db.commit()

    notify_new_run()
    logger.info("Scheduler enqueued run %s for task %s", run_id, task_id)
