import hashlib
import hmac
import json
import math
import re
import secrets
from dataclasses import dataclass
from urllib import error, request

from .settings import settings


@dataclass(frozen=True)
class TariffPlan:
    code: str
    name: str
    price_rub: int
    tokens: int
    description: str


@dataclass(frozen=True)
class GatewayModelDef:
    model_id: str
    provider: str
    label: str
    upstream_model: str
    cost_per_1k_tokens: int


def get_tariff_plans() -> list[TariffPlan]:
    return [
        TariffPlan(
            code="starter",
            name="Starter",
            price_rub=299,
            tokens=150_000,
            description="For personal usage and testing integrations.",
        ),
        TariffPlan(
            code="business",
            name="Business",
            price_rub=999,
            tokens=700_000,
            description="For active products and frequent API traffic.",
        ),
        TariffPlan(
            code="pro",
            name="Pro",
            price_rub=2_499,
            tokens=2_000_000,
            description="For heavy production workloads and proxies.",
        ),
    ]


def get_gateway_models() -> list[GatewayModelDef]:
    return [
        GatewayModelDef(
            model_id="local/qwen2.5-3b",
            provider="ollama",
            label="Qwen 2.5 3B (local)",
            upstream_model=settings.ollama_model,
            cost_per_1k_tokens=1,
        ),
        GatewayModelDef(
            model_id="local/llama3.2-3b",
            provider="ollama",
            label="Llama 3.2 3B (local)",
            upstream_model=settings.ollama_model_alt,
            cost_per_1k_tokens=1,
        ),
        GatewayModelDef(
            model_id="proxy/openai-gpt-4o-mini",
            provider="openai",
            label="OpenAI GPT-4o-mini (proxy)",
            upstream_model="gpt-4o-mini",
            cost_per_1k_tokens=8,
        ),
    ]


def resolve_gateway_model(model_name: str) -> GatewayModelDef | None:
    normalized = model_name.strip().lower()
    for model in get_gateway_models():
        if normalized in {
            model.model_id.lower(),
            model.upstream_model.lower(),
            model.label.lower(),
        }:
            return model
    return None


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 1
    chunks = max(1, math.ceil(len(text) / 4))
    return chunks


def estimate_messages_tokens(messages: list[dict]) -> int:
    combined = "\n".join(str(item.get("content", "")) for item in messages)
    return estimate_text_tokens(combined)


def compute_token_charge(total_tokens: int, cost_per_1k_tokens: int) -> int:
    total = max(1, total_tokens)
    charge = math.ceil(total * cost_per_1k_tokens / 1000)
    return max(1, charge)


def generate_api_key() -> tuple[str, str, str, str]:
    raw = f"asv_{secrets.token_urlsafe(32)}"
    prefix = raw[:16]
    salt = secrets.token_hex(16)
    digest = _hash_value(raw, salt)
    return raw, prefix, salt, digest


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    digest = _hash_value(password, salt)
    return salt, digest


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    digest = _hash_value(password, salt)
    return hmac.compare_digest(digest, expected_hash)


def verify_api_key(raw_key: str, salt: str, expected_hash: str) -> bool:
    digest = _hash_value(raw_key, salt)
    return hmac.compare_digest(digest, expected_hash)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_user_question(question: str) -> str:
    normalized = " ".join(re.findall(r"[a-zA-Zа-яА-Я0-9]+", question.lower())).strip()
    return normalized[:512] if normalized else "unknown"


def call_openai_proxy(
    *,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> tuple[str, int, int, int]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured on gateway")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=settings.openai_base_url,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=90) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI proxy error {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI proxy connection error: {exc}") from exc

    data = json.loads(raw)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI proxy returned empty choices")
    content = choices[0].get("message", {}).get("content", "")
    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or estimate_messages_tokens(messages))
    completion_tokens = int(usage.get("completion_tokens") or estimate_text_tokens(content))
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    return content, prompt_tokens, completion_tokens, total_tokens


def _hash_value(value: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
