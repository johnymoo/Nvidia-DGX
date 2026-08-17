# Benchmark Results - eugr-pr200 Configuration

## Test Environment

- **Date**: 2026-04-23
- **Model**: qwen3.6-35b-fp8
- **Endpoint**: http://localhost:8004/v1/chat/completions
- **Configuration**: eugr-pr200 optimized vLLM config
- **Port**: 8004

## Performance Summary

| Metric | Value |
|--------|-------|
| **Generation Speed** | ~50-51 tok/s |
| **Reasoning Tests Passed** | 5/6 |
| **Reasoning Tests Failed** | 1/6 |

## Test Details

### Speed Tests

| Test Type | Speed (tok/s) |
|-----------|---------------|
| Short Prompt | ~50-51 |
| Medium Prompt | ~50-51 |
| Long Prompt | ~50-51 |

### Reasoning Tests

| Test | Status |
|------|--------|
| Reasoning Test 1 | PASS |
| Reasoning Test 2 | PASS |
| Reasoning Test 3 | PASS |
| Reasoning Test 4 | PASS |
| Reasoning Test 5 | PASS |
| Reasoning Test 6 | FAIL |

## Notes

- The eugr-pr200 configuration uses optimized parameters for the GB10 DGX Spark
- Slightly lower raw speed compared to default config (~70 tok/s) but improved reasoning capability
- 5/6 reasoning tests passing indicates strong reasoning performance

## Comparison with Default Configuration

| Configuration | Speed (tok/s) | Reasoning Pass Rate |
|---------------|----------------|---------------------|
| **eugr-pr200** | ~50-51 | 5/6 |
| Default | ~70 | Not tested |

## Files

- `docker-compose-vllm-fp8-eugr-pr200.yml` - vLLM configuration with eugr-pr200 optimizations
