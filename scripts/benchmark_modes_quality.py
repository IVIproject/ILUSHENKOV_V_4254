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
class ApiCall:
    latency_ms: float
    status_code: int
    raw_text: str
    body_json: dict[str, Any] | None
    error_text: str | None


def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_s: float = 120.0,
    expect_json: bool = True,
) -> ApiCall:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url=url, data=body, headers=req_headers, method="POST")

    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            elapsed = (time.perf_counter() - started) * 1000.0
            parsed = None
            err = None
            try:
                parsed = json.loads(raw)
            except Exception:
                if expect_json:
                    err = "response is not valid JSON"
            return ApiCall(elapsed, resp.status, raw, parsed, err)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        elapsed = (time.perf_counter() - started) * 1000.0
        parsed = None
        err = raw
        try:
            parsed = json.loads(raw)
            if isinstance(parsed.get("detail"), str):
                err = parsed["detail"]
        except Exception:
            pass
        return ApiCall(elapsed, exc.code, raw, parsed, err or f"http error {exc.code}")
    except error.URLError as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        return ApiCall(elapsed, 0, "", None, f"connection error: {exc}")


def _get_json(url: str, headers: dict[str, str] | None = None, timeout_s: float = 30.0) -> dict[str, Any]:
    req = request.Request(url=url, headers=headers or {}, method="GET")
    with request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _register_or_login(base_url: str, email: str, password: str, timeout_s: float) -> str:
    reg = _post_json(
        url=f"{base_url}/gateway/register",
        payload={"email": email, "password": password},
        timeout_s=timeout_s,
    )
    if reg.status_code == 200 and reg.body_json and isinstance(reg.body_json.get("api_key"), str):
        return reg.body_json["api_key"]
    if reg.status_code == 409:
        login = _post_json(
            url=f"{base_url}/gateway/login",
            payload={"email": email, "password": password},
            timeout_s=timeout_s,
        )
        if login.status_code == 200 and login.body_json and isinstance(login.body_json.get("api_key"), str):
            return login.body_json["api_key"]
        raise RuntimeError(f"login failed: {login.status_code} {login.error_text}")
    raise RuntimeError(f"register failed: {reg.status_code} {reg.error_text}")


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    arr = sorted(values)
    if len(arr) == 1:
        return arr[0]
    idx = (len(arr) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(arr) - 1)
    frac = idx - lo
    return arr[lo] * (1 - frac) + arr[hi] * frac


def _domain_quality(item: dict[str, Any], expected_zone: str) -> dict[str, Any]:
    suggestions = item.get("suggestions") if isinstance(item, dict) else None
    if not isinstance(suggestions, list):
        return {"domains_total": 0, "domains_valid_format": 0, "domains_with_zone": 0}
    total = len(suggestions)
    valid = 0
    with_zone = 0
    for value in suggestions:
        if not isinstance(value, str):
            continue
        if " " not in value and "." in value:
            valid += 1
        if value.endswith(expected_zone):
            with_zone += 1
    return {
        "domains_total": total,
        "domains_valid_format": valid,
        "domains_with_zone": with_zone,
    }


def _php_quality(text: str) -> dict[str, Any]:
    text = text or ""
    return {
        "output_size_chars": len(text),
        "contains_php_tag": "<?" in text,
        "contains_html_tag": "<html" in text.lower(),
    }


def _faq_quality(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"matched_items": 0, "relevance_avg": 0.0, "relevance_max": 0.0, "zero_match": True}
    return {
        "matched_items": int(item.get("matched_items", 0)),
        "relevance_avg": float(item.get("relevance_avg", 0.0)),
        "relevance_max": float(item.get("relevance_max", 0.0)),
        "zero_match": bool(item.get("zero_match", True)),
    }


def _run_mode_benchmark(
    *,
    base_url: str,
    key: str,
    model_id: str,
    mode: str,
    payload: dict[str, Any],
    requests_count: int,
    warmup_count: int,
    timeout_s: float,
) -> dict[str, Any]:
    headers = {"X-Gateway-Key": key}
    mode_payload = {"mode": mode, "model_id": model_id, "payload": payload}

    for _ in range(warmup_count):
        _post_json(url=f"{base_url}/mode/run", payload=mode_payload, headers=headers, timeout_s=timeout_s)

    calls: list[ApiCall] = []
    for _ in range(requests_count):
        calls.append(
            _post_json(url=f"{base_url}/mode/run", payload=mode_payload, headers=headers, timeout_s=timeout_s)
        )

    lat = [x.latency_ms for x in calls]
    codes: dict[str, int] = {}
    for x in calls:
        c = str(x.status_code)
        codes[c] = codes.get(c, 0) + 1
    ok = [x for x in calls if 200 <= x.status_code < 300 and isinstance(x.body_json, dict)]

    quality: dict[str, Any] = {}
    if mode == "domains":
        q = [_domain_quality((x.body_json or {}).get("result", {}), payload.get("zone", ".ru")) for x in ok]
        quality = {
            "avg_domains_total": round(statistics.fmean(item["domains_total"] for item in q), 2) if q else 0.0,
            "avg_domains_valid_format": round(statistics.fmean(item["domains_valid_format"] for item in q), 2)
            if q
            else 0.0,
            "avg_domains_with_zone": round(statistics.fmean(item["domains_with_zone"] for item in q), 2)
            if q
            else 0.0,
        }
    elif mode == "chat":
        texts = [
            str((x.body_json or {}).get("result", {}).get("text", ""))
            for x in ok
            if isinstance((x.body_json or {}).get("result"), dict)
        ]
        quality = {
            "avg_answer_length_chars": round(statistics.fmean(len(t) for t in texts), 2) if texts else 0.0,
            "empty_answers": sum(1 for t in texts if not t.strip()),
        }
    elif mode == "support_faq":
        q = [_faq_quality((x.body_json or {}).get("result", {})) for x in ok]
        quality = {
            "avg_matched_items": round(statistics.fmean(item["matched_items"] for item in q), 2) if q else 0.0,
            "avg_relevance": round(statistics.fmean(item["relevance_avg"] for item in q), 4) if q else 0.0,
            "avg_max_relevance": round(statistics.fmean(item["relevance_max"] for item in q), 4) if q else 0.0,
            "zero_match_rate": round(sum(1 for item in q if item["zero_match"]) / len(q), 4) if q else 1.0,
        }

    errors = [x.error_text for x in calls if x.error_text]
    return {
        "mode": mode,
        "model_id": model_id,
        "requests": requests_count,
        "warmup": warmup_count,
        "status_codes": codes,
        "success_rate_percent": round((len(ok) / len(calls) * 100.0), 2) if calls else 0.0,
        "latency_ms": {
            "min": round(min(lat), 2) if lat else 0.0,
            "avg": round(statistics.fmean(lat), 2) if lat else 0.0,
            "median": round(statistics.median(lat), 2) if lat else 0.0,
            "p95": round(_percentile(lat, 0.95), 2) if lat else 0.0,
            "p99": round(_percentile(lat, 0.99), 2) if lat else 0.0,
            "max": round(max(lat), 2) if lat else 0.0,
        },
        "quality": quality,
        "errors": errors[:10],
    }


def _run_php_benchmark(
    *,
    base_url: str,
    model_id: str,
    requests_count: int,
    warmup_count: int,
    timeout_s: float,
) -> dict[str, Any]:
    payload = {
        "template_name": "hosting",
        "content_prompt": "Сделай краткий продающий текст для страницы хостинга.",
        "output_filename": "bench-output.php",
        "model_id": model_id,
    }

    for _ in range(warmup_count):
        _post_json(
            url=f"{base_url}/page-template/generate-file",
            payload=payload,
            timeout_s=timeout_s,
            expect_json=False,
        )

    calls: list[ApiCall] = []
    for _ in range(requests_count):
        calls.append(
            _post_json(
                url=f"{base_url}/page-template/generate-file",
                payload=payload,
                timeout_s=timeout_s,
                expect_json=False,
            )
        )

    lat = [x.latency_ms for x in calls]
    codes: dict[str, int] = {}
    for x in calls:
        c = str(x.status_code)
        codes[c] = codes.get(c, 0) + 1
    ok = [x for x in calls if 200 <= x.status_code < 300]
    php_quality = []
    for x in ok:
        if 200 <= x.status_code < 300:
            php_quality.append(_php_quality(x.raw_text))

    errors = [x.error_text for x in calls if x.error_text]
    return {
        "mode": "php_template_file",
        "model_id": model_id,
        "requests": requests_count,
        "warmup": warmup_count,
        "status_codes": codes,
        "success_rate_percent": round((len(ok) / len(calls) * 100.0), 2) if calls else 0.0,
        "latency_ms": {
            "min": round(min(lat), 2) if lat else 0.0,
            "avg": round(statistics.fmean(lat), 2) if lat else 0.0,
            "median": round(statistics.median(lat), 2) if lat else 0.0,
            "p95": round(_percentile(lat, 0.95), 2) if lat else 0.0,
            "p99": round(_percentile(lat, 0.99), 2) if lat else 0.0,
            "max": round(max(lat), 2) if lat else 0.0,
        },
        "quality": {
            "avg_output_size_chars": round(
                statistics.fmean(item["output_size_chars"] for item in php_quality), 2
            )
            if php_quality
            else 0.0,
            "php_tag_rate": round(
                sum(1 for item in php_quality if item["contains_php_tag"]) / len(php_quality), 4
            )
            if php_quality
            else 0.0,
            "html_tag_rate": round(
                sum(1 for item in php_quality if item["contains_html_tag"]) / len(php_quality), 4
            )
            if php_quality
            else 0.0,
        },
        "errors": errors[:10],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark quality and latency across modes and models."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--email", default="quality.benchmark@example.com")
    parser.add_argument("--password", default="strong-pass-123")
    parser.add_argument(
        "--models",
        default="local/qwen2.5-3b,local/llama3.2-3b",
        help="Use local models for internal modes. Comma-separated model IDs.",
    )
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--admin-api-key",
        default="",
        help="Optional X-API-Key for protected FAQ import endpoints",
    )
    parser.add_argument("--out", default="docs/results/benchmark-modes-quality.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    if not model_ids:
        raise SystemExit("No models provided in --models")

    key = _register_or_login(base_url, args.email, args.password, args.timeout)

    # Seed FAQ so support_faq quality metrics are meaningful.
    faq_items = {
        "items": [
            {
                "question": "Как продлить домен?",
                "answer": "Откройте личный кабинет и перейдите в раздел услуг.",
                "source": "benchmark",
            },
            {
                "question": "Как сменить DNS?",
                "answer": "В карточке домена откройте вкладку DNS и обновите записи.",
                "source": "benchmark",
            },
        ]
    }
    faq_headers = {"X-API-Key": args.admin_api_key} if args.admin_api_key else None
    faq_import = _post_json(
        url=f"{base_url}/support/faq/import",
        payload=faq_items,
        headers=faq_headers,
        timeout_s=args.timeout,
    )

    started_at = datetime.now(timezone.utc).isoformat()
    reports: list[dict[str, Any]] = []

    for model_id in model_ids:
        reports.append(
            _run_mode_benchmark(
                base_url=base_url,
                key=key,
                model_id=model_id,
                mode="chat",
                payload={"prompt": "Коротко опиши преимущества хостинга в 3 пунктах."},
                requests_count=args.requests,
                warmup_count=args.warmup,
                timeout_s=args.timeout,
            )
        )
        reports.append(
            _run_mode_benchmark(
                base_url=base_url,
                key=key,
                model_id=model_id,
                mode="domains",
                payload={
                    "business_context": "облачный хостинг и регистрация доменов",
                    "keywords": ["cloud", "domain", "hosting"],
                    "zone": ".ru",
                    "count": 5,
                },
                requests_count=args.requests,
                warmup_count=args.warmup,
                timeout_s=args.timeout,
            )
        )
        reports.append(
            _run_mode_benchmark(
                base_url=base_url,
                key=key,
                model_id=model_id,
                mode="support_faq",
                payload={"question": "Как продлить домен?", "max_context_items": 3},
                requests_count=args.requests,
                warmup_count=args.warmup,
                timeout_s=args.timeout,
            )
        )
        reports.append(
            _run_php_benchmark(
                base_url=base_url,
                model_id=model_id,
                requests_count=max(3, args.requests // 2),
                warmup_count=max(1, args.warmup // 2),
                timeout_s=args.timeout,
            )
        )

    finished_at = datetime.now(timezone.utc).isoformat()
    result = {
        "started_at": started_at,
        "finished_at": finished_at,
        "base_url": base_url,
        "models": model_ids,
        "faq_import_status": faq_import.status_code,
        "faq_import_error": faq_import.error_text,
        "reports": reports,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nSaved benchmark to: {out_path}")


if __name__ == "__main__":
    main()
