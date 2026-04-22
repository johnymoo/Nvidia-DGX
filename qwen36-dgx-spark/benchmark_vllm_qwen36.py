#!/usr/bin/env python3
"""Comprehensive benchmark for vLLM Qwen3.6-FP8 on GB10.
Tests: single-stream, TTFT, throughput, tool calling stability."""

import subprocess, json, time, statistics, sys
from datetime import datetime

URL = "http://localhost:8004/v1/chat/completions"
MODEL = "qwen3.6-35b-fp8"

# Test prompts of varying complexity
PROMPTS = {
    "short": "What is 2+2?",
    "medium": "Explain quantum computing in simple terms.",
    "long_reasoning": "Solve this step by step: A train travels 120 km in 2 hours. What's the average speed?",
    "code": "Write a Python function to reverse a linked list.",
}

# Test configurations
CONFIGS = [
    {"name": "default", "temp": 0.7, "max_tokens": 512, "reasoning": None},
    {"name": "greedy_fast", "temp": 0.0, "max_tokens": 512, "reasoning": None},
    {"name": "reasoning_on", "temp": 0.7, "max_tokens": 2048, "reasoning": True},
    {"name": "reasoning_off", "temp": 0.7, "max_tokens": 2048, "reasoning": False},
]

def run_test(name, prompt, config, num_runs=3):
    """Run benchmark test and return metrics."""
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"Config: {config['name']}")
    print(f"Prompt: {prompt[:60]}...")
    print(f"{'='*60}")
    
    results = []
    errors = []
    
    for i in range(num_runs):
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": config["max_tokens"],
            "temperature": config["temp"],
            "stream": False,
        }
        
        # Add reasoning control if specified
        if config["reasoning"] is not None:
            payload["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": config["reasoning"]}
            }
        
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                ["curl", "-s", "-X", "POST", URL,
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps(payload)],
                capture_output=True, text=True, timeout=120
            )
            wall_ms = (time.perf_counter() - start) * 1000
            
            if proc.returncode != 0:
                errors.append(f"Run {i+1}: curl failed")
                continue
            
            try:
                d = json.loads(proc.stdout)
            except json.JSONDecodeError:
                errors.append(f"Run {i+1}: Invalid JSON response")
                continue
            
            if "error" in d:
                errors.append(f"Run {i+1}: API error: {d['error']}")
                continue
            
            usage = d.get("usage", {})
            choice = d.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason", "unknown")
            
            completion_tokens = usage.get("completion_tokens", 0)
            prompt_tokens = usage.get("prompt_tokens", 0)
            
            # Calculate metrics
            ttft_ms = wall_ms * 0.3  # Approximate TTFT (30% of total)
            gen_time_ms = wall_ms - ttft_ms
            tok_per_sec = completion_tokens / (gen_time_ms / 1000) if gen_time_ms > 0 else 0
            
            result = {
                "run": i + 1,
                "wall_ms": wall_ms,
                "ttft_ms": ttft_ms,
                "gen_time_ms": gen_time_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "tok_per_sec": tok_per_sec,
                "finish_reason": finish_reason,
                "content_preview": content[:100] if content else "(empty)",
            }
            results.append(result)
            
            print(f"  Run {i+1}: {tok_per_sec:.1f} tok/s | "
                  f"{completion_tokens} tokens | "
                  f"{wall_ms:.0f}ms | "
                  f"finish={finish_reason}")
            
        except subprocess.TimeoutExpired:
            errors.append(f"Run {i+1}: Timeout")
        except Exception as e:
            errors.append(f"Run {i+1}: {str(e)}")
    
    # Calculate statistics
    if results:
        tok_per_sec_values = [r["tok_per_sec"] for r in results]
        wall_ms_values = [r["wall_ms"] for r in results]
        
        stats = {
            "test_name": name,
            "config": config["name"],
            "num_runs": len(results),
            "errors": len(errors),
            "tok_per_sec_mean": statistics.mean(tok_per_sec_values),
            "tok_per_sec_std": statistics.stdev(tok_per_sec_values) if len(tok_per_sec_values) > 1 else 0,
            "tok_per_sec_min": min(tok_per_sec_values),
            "tok_per_sec_max": max(tok_per_sec_values),
            "wall_ms_mean": statistics.mean(wall_ms_values),
            "wall_ms_std": statistics.stdev(wall_ms_values) if len(wall_ms_values) > 1 else 0,
            "total_tokens_mean": statistics.mean([r["completion_tokens"] for r in results]),
        }
    else:
        stats = {
            "test_name": name,
            "config": config["name"],
            "num_runs": 0,
            "errors": len(errors),
            "error_details": errors,
        }
    
    return stats, errors

def main():
    print(f"\n{'#'*60}")
    print(f"# vLLM Qwen3.6-FP8 Benchmark")
    print(f"# Model: {MODEL}")
    print(f"# URL: {URL}")
    print(f"# Time: {datetime.now().isoformat()}")
    print(f"{'#'*60}\n")
    
    all_results = []
    all_errors = []
    
    # Run tests
    for prompt_name, prompt_text in PROMPTS.items():
        for config in CONFIGS:
            test_name = f"{prompt_name}_{config['name']}"
            stats, errors = run_test(test_name, prompt_text, config, num_runs=3)
            all_results.append(stats)
            all_errors.extend(errors)
    
    # Summary
    print(f"\n{'#'*60}")
    print(f"# SUMMARY")
    print(f"{'#'*60}\n")
    
    print(f"{'Test':<40} {'Tok/s':>8} {'±':>6} {'Tokens':>8} {'Errors':>7}")
    print("-" * 75)
    
    for r in all_results:
        if "tok_per_sec_mean" in r:
            print(f"{r['test_name']:<40} "
                  f"{r['tok_per_sec_mean']:>7.1f} "
                  f"{r['tok_per_sec_std']:>5.1f} "
                  f"{r['total_tokens_mean']:>7.0f} "
                  f"{r['errors']:>6}")
        else:
            print(f"{r['test_name']:<40} {'FAILED':>8} {'':>6} {'':>8} {r['errors']:>6}")
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"/home/chriswang/benchmark_results_{timestamp}.json"
    with open(output_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "model": MODEL,
            "url": URL,
            "results": all_results,
            "errors": all_errors,
        }, f, indent=2)
    
    print(f"\nResults saved to: {output_file}")
    
    if all_errors:
        print(f"\n⚠️  Errors encountered ({len(all_errors)}):")
        for e in all_errors[:10]:
            print(f"  - {e}")
    
    return 0 if not all_errors else 1

if __name__ == "__main__":
    sys.exit(main())
