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
    support_faq_total_requests: int
    support_faq_zero_match_total: int
    support_faq_no_match_rate: float
    support_faq_avg_relevance_score: float
    support_faq_top_questions: list[str]
    latest_request_at: datetime | None = None


class GatewayUserRegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=255)
    tariff_code: str = Field(default="starter", min_length=3, max_length=32)


class GatewayUserResponse(BaseModel):
    user_id: int
    email: str
    api_key: str
    token_balance: int
    tariff_code: str


class GatewayTopUpRequest(BaseModel):
    tokens: int = Field(..., ge=1, le=5_000_000)


class GatewayTopUpResponse(BaseModel):
    user_id: int
    token_balance: int


class GatewayTariffItem(BaseModel):
    code: str
    name: str
    monthly_price_rub: int
    included_tokens: int
    overage_price_per_1k_tokens_rub: float
    features: list[str]


class GatewayTariffsResponse(BaseModel):
    tariffs: list[GatewayTariffItem]


class GatewayBalanceResponse(BaseModel):
    user_id: int
    token_balance: int
    tariff_code: str


class GatewayModelItem(BaseModel):
    model_id: str
    display_name: str
    provider: str
    target_model: str
    price_per_1k_tokens: float
    is_active: bool


class GatewayCatalogResponse(BaseModel):
    models: list[GatewayModelItem]


class GatewayChatMessage(BaseModel):
    role: str = Field(..., min_length=3, max_length=16)
    content: str = Field(..., min_length=1, max_length=10000)


class GatewayChatRequest(BaseModel):
    model: str = Field(..., min_length=3, max_length=128)
    messages: list[GatewayChatMessage] = Field(..., min_length=1, max_length=30)
    max_tokens: int = Field(default=300, ge=1, le=4000)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)


class GatewayUsageInfo(BaseModel):
    estimated_input_tokens: int
    estimated_output_tokens: int
    charged_tokens: int
    balance_before: int
    balance_after: int


class GatewayChatResponse(BaseModel):
    provider: str
    model: str
    content: str
    usage: GatewayUsageInfo


class GatewayGenerateRequest(BaseModel):
    model_id: str = Field(..., min_length=3, max_length=128)
    prompt: str = Field(..., min_length=1, max_length=10_000)
    max_tokens: int = Field(default=300, ge=1, le=4000)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)


class GatewayGenerateResponse(BaseModel):
    provider: str
    model_id: str
    answer: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    tokens_spent: int
    token_balance: int


class OpenAIModelCard(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str


class OpenAIModelsResponse(BaseModel):
    object: str = "list"
    data: list[OpenAIModelCard]


class OpenAIChatCompletionsRequest(BaseModel):
    model: str = Field(..., min_length=3, max_length=128)
    messages: list[GatewayChatMessage] = Field(..., min_length=1, max_length=30)
    max_tokens: int = Field(default=300, ge=1, le=4000)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    stream: bool = False
