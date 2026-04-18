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


class PhpTemplateRequest(BaseModel):
    template_html: str = Field(..., min_length=20, max_length=50000)
    content_prompt: str = Field(..., min_length=5, max_length=2000)


class PhpTemplateResponse(BaseModel):
    php_page: str


class SupportFaqImportItem(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    answer: str = Field(..., min_length=3, max_length=4000)
    source: str = Field(default="support_chat", min_length=2, max_length=100)


class SupportFaqImportRequest(BaseModel):
    items: list[SupportFaqImportItem] = Field(..., min_length=1, max_length=500)


class SupportFaqImportResponse(BaseModel):
    imported: int


class SupportDialogsImportResponse(BaseModel):
    imported: int
    parsed_pairs: int


class SupportFaqAskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    max_context_items: int = Field(default=5, ge=1, le=20)


class SupportFaqAskResponse(BaseModel):
    answer: str
    matched_items: int


class ModeRunRequest(BaseModel):
    mode: str = Field(..., description="chat | domains | support_faq")
    payload: dict = Field(default_factory=dict)


class ModeRunResponse(BaseModel):
    mode: str
    result: dict


class PageTemplateGenerateRequest(BaseModel):
    template_name: str = Field(..., min_length=3, max_length=200)
    content_prompt: str = Field(..., min_length=5, max_length=3000)
    output_filename: str = Field(default="generated-page.php", min_length=5, max_length=200)


class SupportDialogsImportRequest(BaseModel):
    transcript: str = Field(..., min_length=10, max_length=200000)


class StatsResponse(BaseModel):
    total_requests: int
    requests_last_24h: int
    average_prompt_length: float
    average_answer_length: float
    latest_request_at: datetime | None = None
