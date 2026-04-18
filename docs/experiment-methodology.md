# Experiment methodology

## Objective
Evaluate practical performance characteristics of `ai-servise` for report and defense:

- API latency for generation requests
- stability of responses (HTTP status distribution)
- growth of service usage metrics (`/stats`)

## Environment

- Runtime: Docker (`api + postgres + nginx`)
- LLM backend: Ollama (`qwen2.5:3b`)
- API endpoint for benchmark by default: `POST /generate`

## Procedure

1. Start services:

```bash
make up
```

2. Verify readiness:

```bash
make health
```

3. Run benchmark script (default 20 measured requests + 3 warmup):

```bash
make benchmark
```

4. Optional domain scenario benchmark:

```bash
python3 scripts/benchmark_api.py \
  --url http://127.0.0.1:8080/mode/run \
  --prompt "chat benchmark prompt" \
  --requests 20 \
  --warmup 3 \
  --out docs/results/benchmark-domains.json
```

5. Save generated JSON files from `docs/results/` and include values in report tables.

## Collected metrics

- total measured requests
- status code distribution
- latency (ms): min, avg, median, p95, p99, max
- average response payload size (bytes)

## Interpretation guidance

- Focus on p95 and p99 for user-visible stability
- Compare `/generate` and `/mode/run` (domains mode) latencies
- Correlate benchmark run with `/stats` values to confirm persistence/observability
