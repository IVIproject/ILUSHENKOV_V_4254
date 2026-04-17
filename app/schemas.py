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


class DomainSuggestionsRequest(BaseModel):
    business_context: str = Field(..., min_length=4, max_length=300)
    keywords: list[str] = Field(default_factory=list, max_length=10)
    zone: str = Field(default=".ru", min_length=2, max_length=10)
    count: int = Field(default=10, ge=1, le=20)


class DomainSuggestionsResponse(BaseModel):
    business_context: str
    zone: str
    suggestions: list[str]


class StatsResponse(BaseModel):
    total_requests: int
    requests_last_24h: int
    average_prompt_length: float
    average_answer_length: float
    latest_request_at: datetime | None = None
