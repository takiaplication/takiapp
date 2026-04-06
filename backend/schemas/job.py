from pydantic import BaseModel
from typing import Optional


class JobResponse(BaseModel):
    id: str
    project_id: str
    job_type: str
    status: str
    progress: float
    progress_message: Optional[str] = None
    error_message: Optional[str] = None
