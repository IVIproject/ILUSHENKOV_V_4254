#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


@dataclass
class CallResult:
    latency_ms: float
    status_code: int
    response_size: int
    body_json: dict[str, Any] | None
    error_text: str | None


def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_s: float,
) -> CallResult:
    final_headers = {"Content-Type": "application/json"}
    if headers:
        final_headers.update(headers)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url=url, data=body, headers=final_headers, method="POST")

    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            latency_ms = (time.perf_counter() - started) * 1000.0
            parsed: dict[str, Any] | None = None
            err: str | None = None
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception:
                err = "response is not valid JSON"
            return CallResult(
                latency_ms=latency_ms,
                status_code=resp.status,
                response_size=len(raw),
                body_json=parsed,
                error_text=err,
            )
    except error.HTTPError as exc:
        raw = exc.read()
        latency_ms = (time.perf_counter() - started) * 1000.0
        parsed: dict[str, Any] | None = None
        err = ""
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            err = raw.decode("utf-8", errors="ignore")
        if parsed and isinstance(parsed.get("detail"), str):
            err = parsed["detail"]
        return CallResult(
            latency_ms=latency_ms,
            status_code=exc.code,
            response_size=len(raw),
            body_json=parsed,
            error_text=err or f"http error {exc.code}",
        )
    except error.URLError as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return CallResult(
            latency_ms=latency_ms,
            status_code=0,
            response_size=0,
            body_json=None,
            error_text=f"connection error: {exc}",
        )


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = (len(sorted_values) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _register_or_login(
    *,
    base_url: str,
    email: str,
    password: str,
    timeout_s: float,
) -> str:
    register_result = _post_json(
        url=f"{base_url}/gateway/register",
        payload={"email": email, "password": password},
        timeout_s=timeout_s,
    )
    if register_result.status_code == 200 and register_result.body_json:
        key = register_result.body_json.get("api_key")
        if isinstance(key, str) and key.strip():
            return key

    if register_result.status_code == 409:
        login_result = _post_json(
            url=f"{base_url}/gateway/login",
            payload={"email": email, "password": password},
            timeout_s=timeout_s,
        )
        if login_result.status_code == 200 and login_result.body_json:
            key = login_result.body_json.get("api_key")
            if isinstance(key, str) and key.strip():
                return key
        raise RuntimeError(f"Login failed: {login_result.status_code} {login_result.error_text}")

    raise RuntimeError(
        f"Register failed: {register_result.status_code} {register_result.error_text}"
    )


def _benchmark_model(
    *,
    base_url: str,
    gateway_key: str,
    model_id: str,
    prompt: str,
    max_tokens: int,
    requests_count: int,
    warmup_count: int,
    timeout_s: float,
) -> dict[str, Any]:
    headers = {"X-Gateway-Key": gateway_key}
    payload = {
        "model_id": model_id,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }

    for _ in range(warmup_count):
        _post_json(
            url=f"{base_url}/gateway/generate",
            payload=payload,
            headers=headers,
            timeout_s=timeout_s,
        )

    results: list[CallResult] = []
    for _ in range(requests_count):
        results.append(
            _post_json(
                url=f"{base_url}/gateway/generate",
                payload=payload,
                headers=headers,
                timeout_s=timeout_s,
            )
        )

    latencies = sorted(item.latency_ms for item in results)
    status_codes: dict[str, int] = {}
    for item in results:
        code = str(item.status_code)
        status_codes[code] = status_codes.get(code, 0) + 1

    successful = [item for item in results if 200 <= item.status_code < 300]
    success_rate = (len(successful) / len(results) * 100.0) if results else 0.0

    prompt_tokens = [
        int(item.body_json.get("prompt_tokens", 0))
        for item in successful
        if item.body_json
    ]
    completion_tokens = [
        int(item.body_json.get("completion_tokens", 0))
        for item in successful
        if item.body_json
    ]
    total_tokens = [
        int(item.body_json.get("total_tokens", 0))
        for item in successful
        if item.body_json
    ]

    errors = [item.error_text for item in results if item.error_text]

    return {
        "model_id": model_id,
        "requests": requests_count,
        "warmup": warmup_count,
        "status_codes": status_codes,
        "success_rate_percent": round(success_rate, 2),
        "latency_ms": {
            "min": round(latencies[0], 2) if latencies else 0.0,
            "avg": round(statistics.fmean(latencies), 2) if latencies else 0.0,
            "median": round(statistics.median(latencies), 2) if latencies else 0.0,
            "p95": round(_percentile(latencies, 0.95), 2) if latencies else 0.0,
            "p99": round(_percentile(latencies, 0.99), 2) if latencies else 0.0,
            "max": round(latencies[-1], 2) if latencies else 0.0,
        },
        "response_size_bytes": {
            "avg": round(statistics.fmean(item.response_size for item in results), 2)
            if results
            else 0.0
        },
        "tokens": {
            "avg_prompt_tokens": round(statistics.fmean(prompt_tokens), 2) if prompt_tokens else 0.0,
            "avg_completion_tokens": round(statistics.fmean(completion_tokens), 2)
            if completion_tokens
            else 0.0,
            "avg_total_tokens": round(statistics.fmean(total_tokens), 2) if total_tokens else 0.0,
        },
        "errors": errors[:10],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark gateway /gateway/generate for several models"
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
        help="Gateway base URL",
    )
    parser.add_argument(
        "--email",
        default="benchmark.user@example.com",
        help="Gateway user email for test login/register",
    )
    parser.add_argument(
        "--password",
        default="strong-pass-123",
        help="Gateway user password",
    )
    parser.add_argument(
        "--models",
        default="local/qwen2.5-3b,local/llama3.2-3b,proxy/openrouter-deepseek-chat",
        help="Comma-separated model IDs",
    )
    parser.add_argument(
        "--prompt",
        default="Сформируй короткий план запуска хостинг-сервиса из 5 пунктов.",
        help="Prompt text for all model calls",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=15,
        help="Measured requests per model",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="Warmup requests per model",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=180,
        help="max_tokens for generation",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Single request timeout in seconds",
    )
    parser.add_argument(
        "--out",
        default="docs/results/benchmark-gateway-3models.json",
        help="Path to save JSON report",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    model_ids = [item.strip() for item in args.models.split(",") if item.strip()]
    if not model_ids:
        raise SystemExit("No models provided in --models")

    gateway_key = _register_or_login(
        base_url=base_url,
        email=args.email,
        password=args.password,
        timeout_s=args.timeout,
    )

    started_at = datetime.now(timezone.utc).isoformat()
    model_reports: list[dict[str, Any]] = []
    for model_id in model_ids:
        report = _benchmark_model(
            base_url=base_url,
            gateway_key=gateway_key,
            model_id=model_id,
            prompt=args.prompt,
            max_tokens=args.max_tokens,
            requests_count=args.requests,
            warmup_count=args.warmup,
            timeout_s=args.timeout,
        )
        model_reports.append(report)

    finished_at = datetime.now(timezone.utc).isoformat()
    result = {
        "started_at": started_at,
        "finished_at": finished_at,
        "base_url": base_url,
        "models": model_reports,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nSaved benchmark to: {out_path}")


if __name__ == "__main__":
    main()
