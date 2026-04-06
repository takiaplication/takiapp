import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from database import get_db
from schemas.job import JobResponse
from services.job_manager import job_manager

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(row)
    finally:
        await db.close()


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    """SSE endpoint for job progress."""

    async def event_generator():
        async for event in job_manager.stream_progress(job_id):
            event_type = event.get("type", "progress")
            data = json.dumps(event)
            yield f"event: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
