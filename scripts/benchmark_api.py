#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request, error


@dataclass
class BenchResult:
    latency_ms: float
    status_code: int
    response_size: int


def post_json(url: str, payload: dict[str, Any], timeout_s: float) -> BenchResult:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            data = resp.read()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return BenchResult(
                latency_ms=elapsed_ms,
                status_code=resp.status,
                response_size=len(data),
            )
    except error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        data = exc.read()
        return BenchResult(
            latency_ms=elapsed_ms,
            status_code=exc.code,
            response_size=len(data),
        )


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = (len(sorted_values) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def run_benchmark(
    url: str,
    payload: dict[str, Any],
    requests_count: int,
    warmup_count: int,
    timeout_s: float,
) -> dict[str, Any]:
    for _ in range(warmup_count):
        post_json(url, payload, timeout_s)

    results: list[BenchResult] = []
    for _ in range(requests_count):
        results.append(post_json(url, payload, timeout_s))

    latencies = sorted(item.latency_ms for item in results)
    codes: dict[int, int] = {}
    for item in results:
        codes[item.status_code] = codes.get(item.status_code, 0) + 1

    avg = statistics.fmean(latencies) if latencies else 0.0
    med = statistics.median(latencies) if latencies else 0.0

    return {
        "url": url,
        "requests": requests_count,
        "warmup": warmup_count,
        "status_codes": codes,
        "latency_ms": {
            "min": round(latencies[0], 2) if latencies else 0.0,
            "avg": round(avg, 2),
            "median": round(med, 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
            "max": round(latencies[-1], 2) if latencies else 0.0,
        },
        "response_size_bytes": {
            "avg": round(statistics.fmean(x.response_size for x in results), 2)
            if results
            else 0.0
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark ai-servise API endpoint")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8080/generate",
        help="Target endpoint URL",
    )
    parser.add_argument(
        "--prompt",
        default="Напиши 2 коротких варианта приветствия для клиента",
        help="Prompt for /generate endpoint",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=20,
        help="Measured requests count",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="Warmup requests count",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Single request timeout in seconds",
    )
    parser.add_argument(
        "--out",
        default="docs/results/benchmark-latest.json",
        help="Path to save benchmark result JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    payload = {"prompt": args.prompt}
    if args.url.endswith("/generate/domains"):
        payload = {
            "business_context": "регистрация доменов и хостинг",
            "keywords": ["domain", "hosting", "cloud"],
            "zone": ".ru",
            "count": 5,
        }

    result = run_benchmark(
        url=args.url,
        payload=payload,
        requests_count=args.requests,
        warmup_count=args.warmup,
        timeout_s=args.timeout,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nSaved benchmark to: {out_path}")


if __name__ == "__main__":
    main()
