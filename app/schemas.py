from datetime import datetime
from pydantic import BaseModel, Field
 
class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
 
class GenerateResponse(BaseModel):
    answer: str


class ErrorResponse(BaseModel):
    detail: str
 
class HistoryItem(BaseModel):
    id: int
    prompt: str
    answer: str
    created_at: datetime


class StreamChunk(BaseModel):
    chunk: str
    done: bool = False
    error: str | None = None
