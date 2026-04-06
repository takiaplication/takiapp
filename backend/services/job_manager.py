import asyncio
import uuid
from datetime import datetime
from typing import Any, Callable, Awaitable, AsyncGenerator

import aiosqlite

from database import get_db


class JobManager:
    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue] = {}

    async def create_job(self, project_id: str, job_type: str) -> str:
        job_id = str(uuid.uuid4())
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO jobs (id, project_id, job_type, status) VALUES (?, ?, ?, 'pending')",
                (job_id, project_id, job_type),
            )
            await db.commit()
        finally:
            await db.close()
        return job_id

    async def submit(
        self,
        job_id: str,
        coro_fn: Callable[..., Awaitable[Any]],
        *args,
        **kwargs,
    ):
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[job_id] = queue

        async def progress_callback(progress: float, message: str = ""):
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE jobs SET status='running', progress=?, progress_message=?, started_at=COALESCE(started_at, CURRENT_TIMESTAMP) WHERE id=?",
                    (progress, message, job_id),
                )
                await db.commit()
            finally:
                await db.close()
            await queue.put({"type": "progress", "progress": progress, "message": message})

        async def run():
            try:
                result = await coro_fn(*args, progress_callback=progress_callback, **kwargs)
                db = await get_db()
                try:
                    await db.execute(
                        "UPDATE jobs SET status='completed', progress=1.0, completed_at=CURRENT_TIMESTAMP WHERE id=?",
                        (job_id,),
                    )
                    await db.commit()
                finally:
                    await db.close()
                await queue.put({"type": "completed", "progress": 1.0, "result": result})
            except Exception as e:
                db = await get_db()
                try:
                    await db.execute(
                        "UPDATE jobs SET status='failed', error_message=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
                        (str(e), job_id),
                    )
                    await db.commit()
                finally:
                    await db.close()
                await queue.put({"type": "error", "message": str(e)})

        task = asyncio.create_task(run())
        self._tasks[job_id] = task

    async def stream_progress(self, job_id: str) -> AsyncGenerator[dict, None]:
        queue = self._queues.get(job_id)
        if not queue:
            yield {"type": "error", "message": "Job not found"}
            return

        while True:
            event = await queue.get()
            yield event
            if event["type"] in ("completed", "error"):
                self._queues.pop(job_id, None)
                self._tasks.pop(job_id, None)
                break


job_manager = JobManager()
