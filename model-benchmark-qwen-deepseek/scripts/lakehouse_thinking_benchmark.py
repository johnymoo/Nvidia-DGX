#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

from quality_benchmark import run_code


HARNESS_ID = "lakehouse-thinking-v2"

SQL_CASES = [
    {
        "id": "cdc_latest_live",
        "prompt": """SQLite table cdc(id TEXT, event_time INT, seq INT, op TEXT, value TEXT) contains change events. op uses I for insert, U for update, and D for delete. Return the latest non-deleted current row for every id as (id, value), ordered by id. A delete is effective only when it is the latest event. Break equal event_time ties by larger seq. Return one SQL code block only.""",
        "setup": "CREATE TABLE cdc(id TEXT,event_time INT,seq INT,op TEXT,value TEXT); INSERT INTO cdc VALUES ('a',10,1,'I','old'),('a',20,1,'U','new'),('b',5,1,'I','keep'),('b',8,1,'D',NULL),('c',7,1,'I','v1'),('c',7,2,'U','v2');",
        "expected": [["a", "new"], ["c", "v2"]],
    },
    {
        "id": "scd2_intervals",
        "prompt": """SQLite table changes(customer_id TEXT, effective_at TEXT, status TEXT) contains SCD changes. Return (customer_id,status,valid_from,valid_to), where valid_to is the next effective_at for that customer or NULL, ordered by customer_id, valid_from. Return one SQL code block only.""",
        "setup": "CREATE TABLE changes(customer_id TEXT,effective_at TEXT,status TEXT); INSERT INTO changes VALUES ('a','2026-01-01','new'),('a','2026-02-10','active'),('a','2026-03-01','paused'),('b','2026-01-05','new'),('b','2026-01-20','active');",
        "expected": [["a","new","2026-01-01","2026-02-10"],["a","active","2026-02-10","2026-03-01"],["a","paused","2026-03-01",None],["b","new","2026-01-05","2026-01-20"],["b","active","2026-01-20",None]],
    },
    {
        "id": "sessionize_events",
        "prompt": """SQLite table events(user_id TEXT, minute INT) contains event timestamps in minutes. A new session starts when the gap from the previous event is greater than 30 minutes. Return (user_id,session_no,start_minute,end_minute,event_count), with session_no starting at 1 per user, ordered by user_id, session_no. Return one SQL code block only.""",
        "setup": "CREATE TABLE events(user_id TEXT,minute INT); INSERT INTO events VALUES ('a',0),('a',10),('a',40),('a',71),('a',75),('b',5),('b',36);",
        "expected": [["a",1,0,40,3],["a",2,71,75,2],["b",1,5,5,1],["b",2,36,36,1]],
    },
    {
        "id": "rolling_revenue",
        "prompt": """SQLite table daily(day TEXT, revenue INT) has one row for each calendar day. Return each day and the inclusive three-row rolling revenue (current day and two preceding days), ordered by day. Return one SQL code block only.""",
        "setup": "CREATE TABLE daily(day TEXT,revenue INT); INSERT INTO daily VALUES ('2026-01-01',10),('2026-01-02',20),('2026-01-03',30),('2026-01-04',40),('2026-01-05',50);",
        "expected": [["2026-01-01",10],["2026-01-02",30],["2026-01-03",60],["2026-01-04",90],["2026-01-05",120]],
    },
    {
        "id": "recursive_hierarchy",
        "prompt": """SQLite table nodes(id TEXT,parent_id TEXT,amount INT) is a forest. Return (root_id,total_amount) for each root, including all descendant amounts, ordered by root_id. Return one SQL code block only.""",
        "setup": "CREATE TABLE nodes(id TEXT,parent_id TEXT,amount INT); INSERT INTO nodes VALUES ('a',NULL,10),('b','a',20),('c','a',30),('d','b',40),('x',NULL,5),('y','x',7);",
        "expected": [["a",100],["x",12]],
    },
    {
        "id": "funnel_first_order",
        "prompt": """SQLite tables users(user_id TEXT,signup_day TEXT) and orders(user_id TEXT,order_day TEXT) are given. Return one row (users_total,converted_7d). A user converts when their first order is on or after signup_day and no more than 7 days later. Orders before signup do not count and later orders cannot replace an earlier valid post-signup order. Return one SQL code block only.""",
        "setup": "CREATE TABLE users(user_id TEXT,signup_day TEXT); CREATE TABLE orders(user_id TEXT,order_day TEXT); INSERT INTO users VALUES ('a','2026-01-01'),('b','2026-01-01'),('c','2026-01-10'),('d','2026-01-10'); INSERT INTO orders VALUES ('a','2025-12-30'),('a','2026-01-03'),('b','2026-01-12'),('c','2026-01-17');",
        "expected": [[4,2]],
    },
]

PYTHON_CASES = [
    ("cdc_deduplicate", "Implement def current_rows(events). Each event is a dict with id, event_time, seq, op, value. Keep the latest by (event_time,seq), omit ids whose latest op is D, and return surviving dicts with only id and value ordered by id. Return Python code only.", [("current_rows([{'id':'a','event_time':1,'seq':1,'op':'I','value':'x'},{'id':'a','event_time':2,'seq':1,'op':'U','value':'y'},{'id':'b','event_time':1,'seq':1,'op':'I','value':'z'},{'id':'b','event_time':2,'seq':1,'op':'D','value':None}])", [{"id":"a","value":"y"}]), ("current_rows([{'id':'a','event_time':2,'seq':1,'op':'U','value':'x'},{'id':'a','event_time':2,'seq':2,'op':'U','value':'y'}])", [{"id":"a","value":"y"}])]),
    ("stable_toposort", "Implement def stable_toposort(graph). graph maps a node to its dependencies. Return a dependency-first order, using original dict insertion order whenever multiple nodes are ready. Raise ValueError for a missing dependency or cycle. Do not mutate the input. Return Python code only.", [("stable_toposort({'publish':['package','test'],'package':['compile'],'test':['lint'],'compile':['lint'],'lint':[],'docs':[]})", ['lint','test','compile','package','publish','docs']), ("(lambda g:(stable_toposort(g),g))({'b':['a'],'a':[]})", [['a','b'],{'b':['a'],'a':[]}]), ("__raises_value_error(lambda: stable_toposort({'a':['missing']}))", True), ("__raises_value_error(lambda: stable_toposort({'a':['b'],'b':['a']}))", True)]),
    ("schema_drift", "Implement def schema_drift(expected, actual). Inputs are nested dicts whose leaves are type strings. Return sorted dotted paths for missing fields, extra fields, or fields whose type differs. A missing/extra nested object reports its leaf paths. Return Python code only.", [("schema_drift({'id':'int','profile':{'name':'str','age':'int'}},{'id':'int','profile':{'name':'str','age':'str','city':'str'}})", ['profile.age','profile.city']), ("schema_drift({'a':{'b':'int','c':'str'}},{})", ['a.b','a.c']), ("schema_drift({}, {'x':{'y':'bool'}})", ['x.y'])]),
    ("bounded_batches", "Implement def bounded_batches(items, max_rows). items is an iterable of (partition,row_count). Preserve order and return a list of batches, each a list of items, whose total rows does not exceed max_rows. An item larger than max_rows must be alone. Reject max_rows <= 0. Consume the iterable once. Return Python code only.", [("bounded_batches([('a',4),('b',6),('c',7),('d',15),('e',2)],10)", [[['a',4],['b',6]],[['c',7]],[['d',15]],[['e',2]]]), ("bounded_batches(iter([('a',3),('b',3),('c',3)]),6)", [[['a',3],['b',3]],[['c',3]]])]),
    ("merge_intervals_payload", "Implement def merge_payload_ranges(items). Each item is (start,end,payload). Sort by start/end. Merge overlapping or touching ranges only when payloads are equal. Return lists [start,end,payload]. Reject start > end. Do not mutate input. Return Python code only.", [("merge_payload_ranges([(5,7,'a'),(1,3,'a'),(3,5,'a'),(7,9,'b'),(9,10,'b')])", [[1,7,'a'],[7,10,'b']]), ("merge_payload_ranges([])", []), ("(lambda x:(merge_payload_ranges(x),x))([(2,3,'x'),(1,1,'x')])", [[[1,1,'x'],[2,3,'x']],[[2,3,'x'],[1,1,'x']]])]),
    ("watermark_commit", "Implement def committable_windows(events, watermark). events is an iterable of dicts with window, event_time, value. Drop late events with event_time <= watermark. For remaining events, return a dict mapping window to values in input order, with window keys inserted in first-seen order. Consume the iterable once and do not mutate events. Return Python code only.", [("committable_windows([{'window':'w1','event_time':10,'value':'a'},{'window':'w2','event_time':8,'value':'b'},{'window':'w1','event_time':12,'value':'c'}],8)", {'w1':['a','c']}), ("committable_windows(iter([{'window':'x','event_time':2,'value':1},{'window':'y','event_time':3,'value':2}]),0)", {'x':[1],'y':[2]})]),
]

INCIDENT_CASES = [
    {"id":"cgroup_oom","evidence":"EV1 kernel: Memory cgroup out of memory: Killed process worker; EV2 memory.current=1073741824 and memory.max=1073741824; EV3 service restarted 14 times; host MemAvailable=48 GiB.","causes":["host_memory_exhaustion","cgroup_memory_limit","disk_pressure"],"actions":["memory_max","swap_zero","restart_backoff","delete_logs"],"expected_cause":"cgroup_memory_limit","expected_actions":{"memory_max","restart_backoff"}},
    {"id":"gpu_cpu_spill","evidence":"EV1 inference log: insufficient GPU memory, moving 9.5 GiB layers to CPU; EV2 container RSS rose from 7 to 61 GiB; EV3 kernel invoked OOM killer; EV4 GPU had another process using 18 GiB.","causes":["gpu_to_cpu_offload","model_corruption","network_loss"],"actions":["disable_cpu_offload","container_memory_limit","vram_guard","increase_swap"],"expected_cause":"gpu_to_cpu_offload","expected_actions":{"disable_cpu_offload","vram_guard"}},
    {"id":"disk_inode_pressure","evidence":"EV1 filesystem blocks 95% used; EV2 inodes 97% used; EV3 deleted-but-open files total 3221225472 bytes; EV4 application reports ENOSPC.","causes":["combined_disk_pressure","database_deadlock","cpu_throttle"],"actions":["bounded_cache_cleanup","restart_file_owner","protect_current_data","recursive_delete_root"],"expected_cause":"combined_disk_pressure","expected_actions":{"bounded_cache_cleanup","restart_file_owner"}},
    {"id":"db_pool_saturation","evidence":"EV1 pool active=40 max=40 wait_p95=2100ms; EV2 database CPU=28%, locks=0, connection count=45/500; EV3 request latency tracks pool wait.","causes":["client_pool_saturation","database_cpu_saturation","lock_contention"],"actions":["bounded_pool_increase","statement_timeout","observe_wait_p95","disable_timeout"],"expected_cause":"client_pool_saturation","expected_actions":{"bounded_pool_increase","observe_wait_p95"}},
    {"id":"iceberg_commit_conflict","evidence":"EV1 two writers read snapshot 812; EV2 writer A commits snapshot 813; EV3 writer B fails ValidationException: conflicting files; EV4 retry on refreshed snapshot succeeds.","causes":["optimistic_commit_conflict","catalog_unavailable","corrupt_manifest"],"actions":["bounded_commit_retry","refresh_snapshot","idempotent_write","delete_metadata"],"expected_cause":"optimistic_commit_conflict","expected_actions":{"bounded_commit_retry","refresh_snapshot"}},
    {"id":"spark_shuffle_skew","evidence":"EV1 median task duration=20s, max=1080s; EV2 one partition has 62% of rows for key UNKNOWN; EV3 executors have free memory and no GC pause; EV4 stage waits for one task.","causes":["shuffle_key_skew","executor_memory_shortage","scheduler_outage"],"actions":["salt_hot_key","adaptive_skew_join","repartition_by_distribution","increase_all_memory"],"expected_cause":"shuffle_key_skew","expected_actions":{"salt_hot_key","adaptive_skew_join"}},
]


def extract_block(text: str, language: str) -> str:
    match = re.search(rf"```(?:{language})?\s*(.*?)```", text, re.I | re.S)
    return (match.group(1) if match else text).strip()


def execute_sql(case: dict, response: str) -> tuple[bool, dict]:
    query = extract_block(response, "sql")
    try:
        connection = sqlite3.connect(":memory:")
        connection.executescript(case["setup"])
        actual = [list(row) for row in connection.execute(query).fetchall()]
        return actual == case["expected"], {"actual": actual, "error": None}
    except Exception as exc:
        return False, {"actual": None, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if "connection" in locals():
            connection.close()


def execute_python(case_id: str, response: str, checks: list[tuple[str, object]]) -> tuple[bool, str]:
    code = extract_block(response, "python")
    if case_id == "stable_toposort":
        code += """

def __raises_value_error(function):
    try:
        function()
    except ValueError:
        return True
    except Exception:
        return False
    return False
"""
    return run_code(code, checks)


def extract_json(text: str) -> dict | None:
    text = extract_block(text, "json")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(text[index:])
                return value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                continue
    return None


def score_incident(case: dict, response: str) -> tuple[float, dict]:
    value = extract_json(response)
    if value is None:
        return 0.0, {"parsed": None, "cause": False, "actions": []}
    cause_ok = value.get("root_cause") == case["expected_cause"]
    selected = set(value.get("action_codes") or [])
    expected = case["expected_actions"]
    correct_actions = len(selected & expected)
    wrong_actions = len(selected - expected)
    action_score = max(0.0, (correct_actions - wrong_actions) / len(expected))
    score = 0.5 * float(cause_ok) + 0.5 * action_score
    return score, {"parsed": value, "cause": cause_ok, "correct_actions": correct_actions, "wrong_actions": wrong_actions}


def request(
    base_url: str,
    model: str,
    prompt: str,
    mode: str,
    max_tokens: int,
    api_key: str | None = None,
    *,
    deepseek_contract: str = "private-vllm",
    deepseek_effort: str | None = None,
    deepseek_sampling: str = "historical",
    force_reasoning_effort_passthrough: bool = False,
    request_timeout: int = 900,
    stream: bool = False,
) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "seed": 42,
    }
    if mode == "off":
        body.update({"temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5})
        body["chat_template_kwargs"] = {"enable_thinking": False}
        body["top_k"] = 20
    elif mode == "deepseek-thinking":
        if deepseek_contract == "online-api":
            if deepseek_sampling != "official-api":
                raise ValueError("online-api DeepSeek thinking requires --deepseek-sampling official-api")
            body["thinking"] = {"type": "enabled"}
        elif deepseek_contract == "private-vllm":
            if deepseek_sampling == "historical":
                body.update({"temperature": 0.6, "top_p": 0.95, "presence_penalty": 0.0})
                body["top_k"] = 20
            elif deepseek_sampling == "official-local-general":
                body.update({"temperature": 1.0, "top_p": 1.0})
            elif deepseek_sampling == "official-local-agent":
                body.update({"temperature": 1.0, "top_p": 0.95})
            else:
                raise ValueError(f"Unsupported private DeepSeek sampling profile: {deepseek_sampling}")
            body["chat_template_kwargs"] = {"thinking": True}
        else:
            raise ValueError(f"Unsupported DeepSeek contract: {deepseek_contract}")
        if deepseek_effort:
            body["reasoning_effort"] = deepseek_effort
            if force_reasoning_effort_passthrough:
                body["allowed_openai_params"] = ["reasoning_effort"]
    else:
        body.update({"temperature": 1.0, "top_p": 0.95, "presence_penalty": 0.0})
        body["chat_template_kwargs"] = {"enable_thinking": True}
        body["top_k"] = 20
        if mode == "qwen38-low":
            body["reasoning_effort"] = "low"
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    started = time.monotonic()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=request_timeout) as response:
            if stream:
                content_parts: list[str] = []
                reasoning_parts: list[str] = []
                finish_reason = None
                usage: dict = {}
                saw_done = False
                first_token_at = None
                last_token_at = None
                first_token_kind = None
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    event = json.loads(data)
                    if event.get("usage"):
                        usage = event["usage"]
                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or {}
                        content = delta.get("content") or ""
                        reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
                        if reasoning or content:
                            token_at = time.monotonic()
                            if first_token_at is None:
                                first_token_at = token_at
                                first_token_kind = "reasoning" if reasoning else "content"
                            last_token_at = token_at
                        content_parts.append(content)
                        reasoning_parts.append(reasoning)
                        if choice.get("finish_reason") is not None:
                            finish_reason = choice["finish_reason"]
                completed = time.monotonic()
                response_seconds = completed - started
                completion_tokens = int(usage.get("completion_tokens", 0))
                decode_tokens = max(completion_tokens - 1, 0)
                ttft_seconds = first_token_at - started if first_token_at is not None else None
                decode_seconds = last_token_at - first_token_at if first_token_at is not None and last_token_at is not None else None
                result = {
                    "response": "".join(content_parts),
                    "reasoning": "".join(reasoning_parts),
                    "finish_reason": finish_reason,
                    "usage": usage,
                    "seconds": round(response_seconds, 3),
                    "ttft_seconds": round(ttft_seconds, 6) if ttft_seconds is not None else None,
                    "response_seconds": round(response_seconds, 6),
                    "decode_seconds": round(decode_seconds, 6) if decode_seconds is not None else None,
                    "decode_tokens_per_second": round(decode_tokens / decode_seconds, 6)
                    if decode_tokens and decode_seconds and decode_seconds > 0 else None,
                    "effective_e2e_completion_tokens_per_second": round(completion_tokens / response_seconds, 6)
                    if completion_tokens and response_seconds > 0 else None,
                    "first_token_kind": first_token_kind,
                }
                if not saw_done or not usage or finish_reason is None:
                    result["finish_reason"] = "error"
                    result["error"] = {
                        "type": "incomplete_stream",
                        "saw_done": saw_done,
                        "has_usage": bool(usage),
                        "has_finish_reason": finish_reason is not None,
                    }
                return result
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        return {
            "response": "",
            "reasoning": "",
            "finish_reason": "error",
            "usage": {},
            "error": {"type": "http", "status": exc.code, "reason": str(exc.reason)},
            "seconds": round(time.monotonic() - started, 3),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "response": "",
            "reasoning": "",
            "finish_reason": "error",
            "usage": {},
            "error": {"type": type(exc).__name__, "reason": str(exc.reason if isinstance(exc, urllib.error.URLError) else exc)},
            "seconds": round(time.monotonic() - started, 3),
        }
    choice = payload["choices"][0]
    message = choice["message"]
    completed = time.monotonic()
    response_seconds = completed - started
    completion_tokens = int((payload.get("usage") or {}).get("completion_tokens", 0))
    return {
        "response": message.get("content") or "",
        "reasoning": message.get("reasoning") or message.get("reasoning_content") or "",
        "finish_reason": choice.get("finish_reason"),
        "usage": payload.get("usage") or {},
        "seconds": round(response_seconds, 3),
        "ttft_seconds": None,
        "response_seconds": round(response_seconds, 6),
        "decode_seconds": None,
        "decode_tokens_per_second": None,
        "effective_e2e_completion_tokens_per_second": round(completion_tokens / response_seconds, 6)
        if completion_tokens and response_seconds > 0 else None,
        "first_token_kind": None,
    }


def incident_prompt(case: dict) -> str:
    return f"""Analyze only this synthetic evidence: {case['evidence']}
Choose root_cause from {case['causes']} and exactly two highest-priority action_codes from {case['actions']}.
Return JSON only: {{"root_cause":"...","action_codes":["..."],"explanation":"brief evidence-based explanation"}}."""


def summarize(rows: list[dict], category: str) -> dict:
    selected = [row for row in rows if row["category"] == category]
    ttft = [float(row["ttft_seconds"]) for row in selected if row.get("ttft_seconds") is not None]
    decode_tps = [float(row["decode_tokens_per_second"]) for row in selected if row.get("decode_tokens_per_second") is not None]
    completion_tokens = sum(row["usage"].get("completion_tokens", 0) for row in selected)
    response_seconds = sum(row["seconds"] for row in selected)
    return {
        "score": sum(row["score"] for row in selected) / len(selected),
        "passed": sum(row["score"] == 1.0 for row in selected),
        "total": len(selected),
        "mean_seconds": statistics.fmean(row["seconds"] for row in selected),
        "completion_tokens": completion_tokens,
        "ttft_seconds_mean": statistics.fmean(ttft) if ttft else None,
        "decode_tokens_per_second_mean": statistics.fmean(decode_tps) if decode_tps else None,
        "effective_e2e_completion_tokens_per_second": completion_tokens / response_seconds if response_seconds else None,
        "length_truncations": sum(row["finish_reason"] == "length" for row in selected),
        "empty_finals": sum(not row["response"] for row in selected),
        "errors": sum(row.get("error") is not None for row in selected),
    }


def metric_summary(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "mean": statistics.fmean(ordered),
        "p50": statistics.median(ordered),
        "p95": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)],
        "max": ordered[-1],
    }


def summarize_performance(rows: list[dict]) -> dict:
    ttft = [float(row["ttft_seconds"]) for row in rows if row.get("ttft_seconds") is not None]
    response = [
        float(row["response_seconds"] if row.get("response_seconds") is not None else row["seconds"])
        for row in rows
    ]
    decode_tps = [float(row["decode_tokens_per_second"]) for row in rows if row.get("decode_tokens_per_second") is not None]
    completion_tokens = sum(int(row.get("usage", {}).get("completion_tokens", 0)) for row in rows)
    return {
        "requests": len(rows),
        "ttft_available_requests": len(ttft),
        "ttft_seconds": metric_summary(ttft),
        "response_seconds": metric_summary(response),
        "decode_tokens_per_second": metric_summary(decode_tps),
        "total_completion_tokens": completion_tokens,
        "effective_e2e_completion_tokens_per_second": completion_tokens / sum(response),
    }


def compact_text(value: str, max_chars: int) -> tuple[str, dict]:
    digest = hashlib.sha256(value.encode()).hexdigest()
    metadata = {
        "chars": len(value),
        "sha256": digest,
        "storage_truncated": False,
    }
    if max_chars <= 0 or len(value) <= max_chars:
        return value, metadata
    metadata["storage_truncated"] = True
    suffix = f"\n\n[stored prefix truncated; full_sha256={digest}; full_chars={len(value)}]"
    return value[: max(0, max_chars - len(suffix))] + suffix, metadata


def compact_row(row: dict, max_response_chars: int, max_reasoning_chars: int) -> dict:
    compacted = dict(row)
    for field, max_chars in (("response", max_response_chars), ("reasoning", max_reasoning_chars)):
        value = str(compacted.get(field) or "")
        compacted[field], metadata = compact_text(value, max_chars)
        compacted[f"{field}_evidence"] = metadata
    return compacted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--mode", choices=["off", "qwen36-thinking", "qwen38-low", "deepseek-thinking"], required=True)
    parser.add_argument("--api-key-env", help="Name of an environment variable containing an optional OpenAI-compatible API key")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--request-timeout", type=int, default=900)
    parser.add_argument("--stream", action="store_true", help="Use server-sent event streaming for the request")
    parser.add_argument("--deepseek-contract", choices=["private-vllm", "online-api"], default="private-vllm")
    parser.add_argument("--deepseek-effort", choices=["low", "high", "max"])
    parser.add_argument(
        "--force-reasoning-effort-passthrough",
        action="store_true",
        help="Tell a LiteLLM proxy to forward reasoning_effort to an OpenAI-compatible upstream",
    )
    parser.add_argument("--deepseek-sampling", choices=["historical", "official-api", "official-local-general", "official-local-agent"], default="historical")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--expected-runs", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1, help="Maximum concurrent model requests")
    parser.add_argument("--category", choices=["all", "sql", "python", "incident"], default="all")
    parser.add_argument("--treatment", help="Stable treatment label used when aggregating matrix results")
    parser.add_argument("--endpoint-label", help="Safe endpoint identifier recorded in output instead of --base-url")
    parser.add_argument("--max-response-chars", type=int, default=0, help="Store a prefix of final content; zero stores all content")
    parser.add_argument("--max-reasoning-chars", type=int, default=0, help="Store a prefix of reasoning; zero stores all content")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_tokens < 256:
        parser.error("--max-tokens must be at least 256")
    if args.request_timeout < 30:
        parser.error("--request-timeout must be at least 30 seconds")
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    if args.expected_runs < 1:
        parser.error("--expected-runs must be at least 1")
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if args.max_response_chars < 0 or args.max_reasoning_chars < 0:
        parser.error("evidence character limits cannot be negative")
    if args.mode != "deepseek-thinking" and args.deepseek_effort:
        parser.error("--deepseek-effort is only valid for --mode deepseek-thinking")
    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not api_key:
        parser.error(f"environment variable {args.api_key_env} is empty")

    request_specs = [
        ("sql", case["id"], case["prompt"], case)
        for case in SQL_CASES
    ]
    request_specs.extend(
        ("python", case_id, prompt, (case_id, checks))
        for case_id, prompt, checks in PYTHON_CASES
    )
    request_specs.extend(
        ("incident", case["id"], incident_prompt(case), case)
        for case in INCIDENT_CASES
    )
    if args.category != "all":
        request_specs = [spec for spec in request_specs if spec[0] == args.category]

    def run_model_request(spec: tuple[str, str, str, object]) -> dict:
        return request(
            args.base_url,
            args.model,
            spec[2],
            args.mode,
            args.max_tokens,
            api_key,
            deepseek_contract=args.deepseek_contract,
            deepseek_effort=args.deepseek_effort,
            deepseek_sampling=args.deepseek_sampling,
            force_reasoning_effort_passthrough=args.force_reasoning_effort_passthrough,
            request_timeout=args.request_timeout,
            stream=args.stream,
        )

    responses: list[dict | None] = [None] * len(request_specs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(run_model_request, spec): index
            for index, spec in enumerate(request_specs)
        }
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            responses[index] = future.result()
            print(
                json.dumps({
                    "id": request_specs[index][1],
                    "request_complete": True,
                    "seconds": responses[index]["seconds"],
                    "finish_reason": responses[index]["finish_reason"],
                }),
                flush=True,
            )

    rows = []
    for spec, response in zip(request_specs, responses):
        category, case_id, prompt, source = spec
        if response is None:
            raise RuntimeError(f"request result missing for {case_id}")
        row = response
        if category == "sql":
            case = source
            passed, detail = execute_sql(case, row["response"])
            rows.append(compact_row({"id": case["id"], "category": "sql", "prompt": case["prompt"], "expected": case["expected"], "score": float(passed), "passed": passed, "detail": detail, **row}, args.max_response_chars, args.max_reasoning_chars))
            score = float(passed)
        elif category == "python":
            _case_id, checks = source
            passed, executor_tail = execute_python(case_id, row["response"], checks)
            rows.append(compact_row({"id": case_id, "category": "python", "prompt": prompt, "score": float(passed), "passed": passed, "detail": {"executor_tail": executor_tail}, **row}, args.max_response_chars, args.max_reasoning_chars))
            score = float(passed)
        else:
            case = source
            score, detail = score_incident(case, row["response"])
            rows.append(compact_row({"id": case["id"], "category": "incident", "prompt": prompt, "expected": {"root_cause": case["expected_cause"], "action_codes": sorted(case["expected_actions"])}, "score": score, "passed": score == 1.0, "detail": detail, **row}, args.max_response_chars, args.max_reasoning_chars))
        print(json.dumps({"id": case_id, "score": score, "seconds": row["seconds"]}), flush=True)

    categories = {
        name: summarize(rows, name)
        for name in ("sql", "python", "incident")
        if any(row["category"] == name for row in rows)
    }
    result = {
        "schema_version": 2,
        "harness_id": HARNESS_ID,
        "status": "passed",
        "tag": args.tag,
        "treatment": args.treatment or args.tag,
        "model": args.model,
        "base_url": args.endpoint_label or args.base_url,
        "mode": args.mode,
        "seed": 42,
        "repeat": args.repeat,
        "expected_runs": args.expected_runs,
        "category_filter": args.category,
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "sampling": (
            f"DeepSeek {args.deepseek_contract}; {args.deepseek_sampling}; effort={args.deepseek_effort or 'default'}"
            if args.mode == "deepseek-thinking"
            else "official precise-coding thinking parameters"
            if args.mode != "off"
            else "official non-thinking parameters"
        ),
        "request_config": {
            "deepseek_contract": args.deepseek_contract if args.mode == "deepseek-thinking" else None,
            "deepseek_effort": args.deepseek_effort if args.mode == "deepseek-thinking" else None,
            "deepseek_sampling": args.deepseek_sampling if args.mode == "deepseek-thinking" else None,
            "force_reasoning_effort_passthrough": args.force_reasoning_effort_passthrough,
            "max_response_chars": args.max_response_chars,
            "max_reasoning_chars": args.max_reasoning_chars,
            "request_timeout_seconds": args.request_timeout,
            "concurrency": args.concurrency,
            "stream": args.stream,
        },
        "categories": categories,
        "performance": summarize_performance(rows),
        "macro_score": statistics.fmean(value["score"] for value in categories.values()),
        "total_seconds": sum(row["seconds"] for row in rows),
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"tag": args.tag, "macro_score": result["macro_score"], "categories": categories}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
