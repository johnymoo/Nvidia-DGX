#!/usr/bin/env python3
"""Run and render the bounded MiniMax H3 benchmark using only stdlib tools."""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temp.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def api_json(base, endpoint, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base + endpoint, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def api_post(base, endpoint, payload, timeout=30):
    request = urllib.request.Request(
        base + endpoint, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"POST {endpoint} returned {response.status}")


def command_json(command):
    return json.loads(subprocess.check_output(command, text=True))


def status(root):
    return command_json([str(root / "execution/minimax-h3/status-comfyui.sh"),
                         "--root", str(root)])


def public_runtime(value):
    protected = value["protected"]["observed"]
    return {
        "pid": value["pid"], "start_ticks": value["start_ticks"],
        "boot_id": value["boot_id"], "started_at": value["started_at"],
        "http_code": value["http_code"], "listener": value["listener"],
        "protected": {"container_id": protected["container_id"],
                      "health": protected["health"],
                      "restart_count": protected["restart_count"]},
    }


def assert_runtime(expected, observed):
    keys = ("pid", "start_ticks", "boot_id", "listener")
    if any(expected.get(key) != observed.get(key) for key in keys):
        raise RuntimeError("ComfyUI process or listener identity changed")
    if observed.get("http_code") != "200" or not observed.get("protected", {}).get("matches"):
        raise RuntimeError("ComfyUI or protected service is unhealthy")


def assert_idle(base):
    queue = api_json(base, "/queue")
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI queue is not idle; refusing to submit")
    return queue


def build_prompt(template, case, profile, prefix):
    prompt = copy.deepcopy(template)
    prompt["104"]["inputs"].update(
        prompt=case["prompt"], width=profile["width"],
        height=profile["height"], length=profile["frames"])
    prompt["9"]["inputs"]["steps"] = profile["steps"]
    prompt["15"]["inputs"]["noise_seed"] = case["seed"]
    prompt["92"]["inputs"]["filename_prefix"] = f"{prefix}/{case['id']}/video"
    prompt["200"] = {"class_type": "ImageFromBatch", "inputs": {
        "image": ["10", 0], "batch_index": 0, "length": 1}}
    prompt["201"] = {"class_type": "SaveImage", "inputs": {
        "images": ["200", 0], "filename_prefix": f"{prefix}/{case['id']}/frame"}}
    return prompt


def extract_outputs(history, prompt_id, root):
    record = history[prompt_id]
    outputs = []
    for node, kind in (("92", "video"), ("201", "image")):
        rows = record.get("outputs", {}).get(node, {}).get("images", [])
        if len(rows) != 1:
            raise RuntimeError(f"expected one {kind} output, found {len(rows)}")
        row = rows[0]
        if row.get("type") != "output":
            raise RuntimeError("unexpected output type")
        relative = Path(row.get("subfolder", "")) / row["filename"]
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("unsafe output path")
        path = (root / "output" / relative).resolve(strict=True)
        if root.joinpath("output").resolve() not in path.parents:
            raise RuntimeError("output escaped root")
        outputs.append((kind, path))
    return dict(outputs)


def media_probe(path, ffmpeg):
    process = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-"],
        text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    duration_match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", process.stderr)
    video_match = re.search(
        r"Video:\s*([^,]+).*?\b(\d+)x(\d+)\b.*?\b([0-9.]+) fps\b",
        process.stderr)
    if not duration_match or not video_match:
        raise RuntimeError("unable to parse bundled FFmpeg media diagnostics")
    hours, minutes, seconds = duration_match.groups()
    return {
        "format": {"duration": str(
            int(hours) * 3600 + int(minutes) * 60 + float(seconds))},
        "streams": [{"codec_type": "video",
                     "codec_name": video_match.group(1).strip(),
                     "width": int(video_match.group(2)),
                     "height": int(video_match.group(3)),
                     "avg_frame_rate": video_match.group(4)}],
        "source": "bundled_ffmpeg_diagnostics",
    }


def pixel_hash_image(path, ffmpeg):
    data = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(path),
                                    "-frames:v", "1", "-f", "rawvideo",
                                    "-pix_fmt", "rgb24", "-"])
    return hashlib.sha256(data).hexdigest()


def frame_sequence_hash(path, ffmpeg):
    process = subprocess.Popen([ffmpeg, "-v", "error", "-i", str(path),
                                "-map", "0:v:0", "-f", "rawvideo",
                                "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    digest = hashlib.sha256()
    for block in iter(lambda: process.stdout.read(1024 * 1024), b""):
        digest.update(block)
    if process.wait() != 0:
        raise RuntimeError("video decode failed")
    return digest.hexdigest()


def resource_sample(pid):
    meminfo = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        meminfo[key] = int(value.strip().split()[0])
    rss_kb = None
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
    except FileNotFoundError:
        pass
    gpu = temperature = power_watts = None
    try:
        row = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"], text=True,
            stderr=subprocess.DEVNULL).strip().splitlines()[0].split(",")
        values = [item.strip() for item in row]
        gpu = int(values[0]) if values[0] not in ("N/A", "[N/A]") else None
        temperature = int(values[1]) if values[1] not in ("N/A", "[N/A]") else None
        power_watts = float(values[2]) if values[2] not in ("N/A", "[N/A]") else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return {"at": utc_now(), "available_memory_kib": meminfo.get("MemAvailable"),
            "comfyui_rss_kib": rss_kb, "gpu_utilization_percent": gpu,
            "gpu_temperature_celsius": temperature,
            "gpu_power_draw_watts": power_watts}


def sample_until(stop_event, pid, target):
    while not stop_event.is_set():
        target.append(resource_sample(pid))
        stop_event.wait(1)


def event_times(history, prompt_id):
    messages = history[prompt_id].get("status", {}).get("messages", [])
    result = {}
    for row in messages:
        if isinstance(row, list) and len(row) > 1 and isinstance(row[1], dict):
            event = row[0]
            if event in ("execution_start", "execution_success", "execution_error"):
                result[event] = row[1].get("timestamp")
            elif event == "execution_cached":
                result["execution_cached_nodes"] = row[1].get("nodes", [])
    return result


def event_duration_seconds(events):
    start = events.get("execution_start")
    success = events.get("execution_success")
    if not isinstance(start, (int, float)) or not isinstance(success, (int, float)):
        return None
    # ComfyUI event timestamps are milliseconds since Unix epoch.
    return round((success - start) / 1000, 3)


def run_case(base, root, template, case, profile, run_id, artifacts, ffmpeg, canary=False):
    assert_idle(base)
    api_post(base, "/free", {"free_memory": True})
    time.sleep(2)
    assert_idle(base)
    prefix = f"benchmark/{run_id}/{'canary-' if canary else ''}{profile['id']}"
    prompt = build_prompt(template, case, profile, prefix)
    case_dir = artifacts / ("canary" if canary else "cases") / case["id"] / profile["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    write_json(case_dir / "prompt.json", prompt)
    client_id = f"h3-benchmark-{run_id}-{case['id']}-{profile['id']}"
    submitted_wall, submitted_mono = utc_now(), time.monotonic()
    response = api_json(base, "/prompt", {"prompt": prompt, "client_id": client_id})
    accepted_wall, accepted_mono = utc_now(), time.monotonic()
    write_json(case_dir / "queue-response.json", response)
    prompt_id = response["prompt_id"]
    samples, stop_event = [], threading.Event()
    runtime = status(root)
    sampler = threading.Thread(target=sample_until,
                               args=(stop_event, runtime["pid"], samples), daemon=True)
    sampler.start()
    deadline = time.monotonic() + 3600
    history = {}
    try:
        while time.monotonic() < deadline:
            history = api_json(base, f"/history/{prompt_id}")
            if prompt_id in history:
                state = history[prompt_id].get("status", {})
                if state.get("completed"):
                    if state.get("status_str") != "success":
                        raise RuntimeError(f"prompt ended as {state.get('status_str')}")
                    break
            time.sleep(2)
        else:
            raise TimeoutError("prompt did not complete within 3600 seconds")
        observed_wall, observed_mono = utc_now(), time.monotonic()
        time.sleep(10)
    finally:
        stop_event.set()
        sampler.join(5)
    write_json(case_dir / "history.json", history)
    write_json(case_dir / "resources.json", samples)
    outputs = extract_outputs(history, prompt_id, root)
    metadata = media_probe(outputs["video"], ffmpeg)
    video_hash = sha256(outputs["video"])
    sequence_hash = frame_sequence_hash(outputs["video"], ffmpeg)
    image_hash = sha256(outputs["image"])
    image_pixel_hash = pixel_hash_image(outputs["image"], ffmpeg)
    video_first_pixel_hash = pixel_hash_image(outputs["video"], ffmpeg)
    timing = event_times(history, prompt_id)
    cached_nodes = timing.get("execution_cached_nodes", [])
    critical_nodes = {"104", "15", "9", "14", "10", "91", "92", "200", "201"}
    if critical_nodes.intersection(cached_nodes):
        raise RuntimeError(
            "critical generation nodes were cached after execution cache reset")
    result = {
        "id": case["id"], "title": case["title"], "category": case["category"],
        "prompt": case["prompt"], "seed": case["seed"], "profile": profile,
        "status": "success", "prompt_id": prompt_id, "client_id": client_id,
        "timing": {"submitted_at": submitted_wall, "accepted_at": accepted_wall,
                   "completed_observed_at": observed_wall,
                   "acceptance_delay_seconds": round(accepted_mono - submitted_mono, 3),
                   "bounded_wall_seconds": round(observed_mono - accepted_mono, 3),
                   "comfyui_execution_seconds": event_duration_seconds(timing),
                   "critical_generation_nodes_cached": False,
                   "comfyui_events": timing},
        "video": {"source_path": str(outputs["video"]), "bytes": outputs["video"].stat().st_size,
                  "sha256": video_hash, "decoded_rgb_sequence_sha256": sequence_hash,
                  "ffprobe": metadata},
        "image": {"source_path": str(outputs["image"]), "bytes": outputs["image"].stat().st_size,
                  "sha256": image_hash, "decoded_rgb_sha256": image_pixel_hash,
                  "video_first_frame_decoded_rgb_sha256": video_first_pixel_hash,
                  "pixel_equal_after_lossy_video_encode": image_pixel_hash == video_first_pixel_hash,
                  "source_lineage": {"decoded_image_node": "10", "selector_node": "200",
                                     "save_image_node": "201", "video_node": "91",
                                     "save_video_node": "92", "same_prompt_id": prompt_id}},
        "resources": samples,
        "evidence_dir": str(case_dir),
    }
    write_json(case_dir / "receipt.json", result)
    return result


def bounded_scan(path, offset, patterns):
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            text = handle.read().decode(errors="replace")
    except OSError as exc:
        return {"status": "unknown", "reason": str(exc), "matches": []}
    matches = [line for line in text.splitlines()
               if any(pattern.lower() in line.lower() for pattern in patterns)]
    return {"status": "passed" if not matches else "failed", "matches": matches[-100:]}


def run(args):
    root, out = Path(args.root).resolve(), Path(args.output).resolve()
    base = f"http://127.0.0.1:{args.port}"
    config, template = read_json(args.cases), read_json(args.workflow)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifacts = out / "runs" / run_id
    artifacts.mkdir(parents=True)
    initial_status = status(root)
    if not initial_status.get("running") or not initial_status.get("identity_match"):
        raise RuntimeError("ComfyUI runtime identity is not accepted")
    if not initial_status.get("listener_match") or initial_status.get("http_code") != "200":
        raise RuntimeError("ComfyUI listener is not accepted")
    if not initial_status.get("protected", {}).get("matches"):
        raise RuntimeError("protected service does not match baseline")
    assert_idle(base)
    initial_public = public_runtime(initial_status)
    log_path = Path(initial_status["active_log"])
    log_offset = log_path.stat().st_size
    started_at = utc_now()
    ffmpeg = subprocess.check_output(
        [str(root / "venv/bin/python"), "-c",
         "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"], text=True).strip()
    subject = root / "execution/minimax-h3/deployment-subject.tsv"
    report = {
        "schema_version": 1, "run_id": run_id, "status": "running",
        "started_at": started_at, "host": os.uname().nodename,
        "deployment": {"gitee_revision": "9f9eca9589d4b4c0a01a8081c8c4add279e18868",
                       "comfyui_revision": subprocess.check_output(
                           ["git", "-C", str(root / "comfy/ComfyUI"), "rev-parse", "HEAD"], text=True).strip(),
                       "subject_sha256": sha256(subject), "runtime_before": initial_public},
        "profile_attempts": [], "cases": [], "fatal_scans": {},
    }
    write_json(artifacts / "benchmark.json", report)
    canary_case = dict(config["cases"][0])
    canary_case["id"] = "canary"
    selected = None
    for profile in config["profiles"]:
        attempt = {"profile": profile, "started_at": utc_now()}
        try:
            result = run_case(base, root, template, canary_case, profile, run_id,
                              artifacts, ffmpeg, canary=True)
            attempt.update(status="success", receipt=result["evidence_dir"] + "/receipt.json")
            selected = profile
        except Exception as exc:
            attempt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        report["profile_attempts"].append(attempt)
        write_json(artifacts / "benchmark.json", report)
        if selected:
            break
    if selected is None:
        report.update(status="failed", completed_at=utc_now(), error="all canary profiles failed")
        write_json(artifacts / "benchmark.json", report)
        raise RuntimeError(report["error"])
    report["selected_profile"] = selected
    for case in config["cases"]:
        try:
            result = run_case(base, root, template, case, selected, run_id,
                              artifacts, ffmpeg)
            report["cases"].append(result)
        except Exception as exc:
            report["cases"].append({"id": case["id"], "title": case["title"],
                                    "category": case["category"], "prompt": case["prompt"],
                                    "seed": case["seed"], "profile": selected,
                                    "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            write_json(artifacts / "benchmark.json", report)
            if not status(root).get("protected", {}).get("matches"):
                break
        write_json(artifacts / "benchmark.json", report)
    time.sleep(10)
    final_status = status(root)
    assert_runtime(initial_public, final_status)
    patterns = ["traceback", "cuda error", "out of memory", "oom", "xid", "worker lost"]
    report["fatal_scans"]["comfyui"] = bounded_scan(log_path, log_offset, patterns)
    try:
        kernel = subprocess.check_output(["journalctl", "-k", "--since", started_at,
                                          "--no-pager"], text=True, stderr=subprocess.STDOUT)
        kernel_path = artifacts / "kernel.log"
        kernel_path.write_text(kernel)
        report["fatal_scans"]["kernel"] = bounded_scan(kernel_path, 0, patterns)
    except subprocess.CalledProcessError as exc:
        report["fatal_scans"]["kernel"] = {"status": "unknown", "reason": exc.output[-1000:], "matches": []}
    successful = [case for case in report["cases"] if case["status"] == "success"]
    by_id = {case["id"]: case for case in successful}
    repro = None
    if "repro-a" in by_id and "repro-b" in by_id:
        repro = {
            "bitstream_equal": by_id["repro-a"]["video"]["sha256"] == by_id["repro-b"]["video"]["sha256"],
            "decoded_frames_equal": by_id["repro-a"]["video"]["decoded_rgb_sequence_sha256"] == by_id["repro-b"]["video"]["decoded_rgb_sequence_sha256"],
        }
    report.update(
        completed_at=utc_now(), runtime_after=public_runtime(final_status),
        reproducibility=repro,
        summary={"successful": len(successful), "total": len(report["cases"]),
                 "sequential_success": all(by_id.get(f"stability-{i}") for i in range(1, 4))})
    scans_pass = all(scan["status"] == "passed" for scan in report["fatal_scans"].values())
    report["status"] = "passed" if len(successful) == len(report["cases"]) and scans_pass else "partial"
    write_json(artifacts / "benchmark.json", report)
    latest = out / "latest.json"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to((artifacts / "benchmark.json").relative_to(out))
    print(artifacts / "benchmark.json")


def media_info(case):
    streams = case.get("video", {}).get("ffprobe", {}).get("streams", [])
    video = next((row for row in streams if row.get("codec_type") == "video"), {})
    duration = case.get("video", {}).get("ffprobe", {}).get("format", {}).get("duration")
    return f"{video.get('width', '?')}x{video.get('height', '?')} · {float(duration or 0):.1f}s"


def render(args):
    data, site = read_json(args.input), Path(args.site).resolve()
    if site.exists():
        shutil.rmtree(site)
    assets = site / "assets"
    assets.mkdir(parents=True)
    cases = []
    for case in data["cases"]:
        item = copy.deepcopy(case)
        if case["status"] == "success":
            for key, suffix in (("video", ".mp4"), ("image", ".png")):
                source = Path(case[key]["source_path"]).resolve(strict=True)
                target = assets / f"{case['id']}{suffix}"
                shutil.copy2(source, target)
                item[key]["site_path"] = f"assets/{target.name}"
        cases.append(item)
    data["cases"] = cases
    write_json(site / "benchmark.json", data)
    css = """*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:#171717;background:#fff;font:15px/1.55 Inter,system-ui,sans-serif;letter-spacing:0}a{color:inherit}nav{position:sticky;top:0;z-index:5;background:rgba(255,255,255,.96);border-bottom:1px solid #ddd}nav div{max-width:1180px;margin:auto;height:56px;display:flex;align-items:center;gap:22px;padding:0 24px;overflow-x:auto;white-space:nowrap}.brand{font-weight:750;margin-right:auto}.accent{color:#d5292f}.hero{min-height:78vh;background:#171717;color:#fff;display:grid;grid-template-columns:minmax(0,1fr) minmax(420px,1.25fr);align-items:center;gap:44px;padding:54px max(24px,calc((100vw - 1180px)/2)) 42px}.hero h1{font-size:clamp(38px,5vw,72px);line-height:1.02;margin:10px 0 18px;letter-spacing:0}.eyebrow,.kicker{text-transform:uppercase;font-size:12px;font-weight:750;color:#e8464c}.lede{color:#bbb;max-width:620px;font-size:18px}.hero video{width:100%;aspect-ratio:16/10;object-fit:cover;background:#050505}.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:#444;margin-top:30px}.metric{background:#171717;padding:16px}.metric b{display:block;font-size:25px}.metric span{color:#aaa;font-size:12px}.band{padding:72px max(24px,calc((100vw - 1180px)/2));border-bottom:1px solid #ddd}.band h2{font-size:34px;margin:0 0 12px}.intro{max-width:760px;color:#555;margin:0 0 32px}.gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.case{border:1px solid #ccc;border-radius:6px;overflow:hidden;background:#fff}.media{position:relative;aspect-ratio:16/9;background:#111}.media video,.media img{width:100%;height:100%;object-fit:cover}.case-body{padding:18px}.case h3{margin:2px 0 8px;font-size:20px}.meta{display:flex;justify-content:space-between;color:#666;font-size:12px}.prompt{color:#555}.status{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700}.dot{width:7px;height:7px;border-radius:50%;background:#27834c}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid #ddd;vertical-align:top}th{font-size:12px;color:#666}code,pre{font:12px/1.5 ui-monospace,monospace}pre{padding:16px;background:#f5f5f5;overflow:auto;border-left:3px solid #d5292f}.limit{display:grid;grid-template-columns:repeat(3,1fr);gap:28px}.limit h3{font-size:16px}footer{padding:30px max(24px,calc((100vw - 1180px)/2));color:#666}.hash{word-break:break-all;font-family:ui-monospace,monospace;font-size:11px}details{border-top:1px solid #ddd;padding:15px 0}summary{cursor:pointer;font-weight:700}@media(max-width:800px){.hero{min-height:auto;grid-template-columns:1fr;padding-top:44px}.hero video{order:-1}.gallery,.limit{grid-template-columns:1fr}.band{padding-top:48px;padding-bottom:48px}}@media(max-width:480px){nav div{padding:0 16px}.hero,.band{padding-left:16px;padding-right:16px}.metrics{grid-template-columns:1fr 1fr}.hero h1{font-size:40px}.gallery{gap:16px}}"""
    (site / "style.css").write_text(css)
    ok = [case for case in cases if case["status"] == "success"]
    featured = ok[0] if ok else None
    cards = []
    for case in cases:
        if case["status"] == "success":
            cards.append(f'''<article class="case" id="{case['id']}"><div class="media"><video controls preload="metadata" poster="{case['image']['site_path']}"><source src="{case['video']['site_path']}" type="video/mp4"></video></div><div class="case-body"><div class="meta"><span>{html.escape(case['category'])}</span><span>{media_info(case)}</span></div><h3>{html.escape(case['title'])}</h3><p class="prompt">{html.escape(case['prompt'])}</p><div class="meta"><span class="status"><i class="dot"></i>Completed</span><span>{case['timing']['bounded_wall_seconds']:.1f}s bounded wall</span></div></div></article>''')
        else:
            cards.append(f'''<article class="case"><div class="case-body"><div class="status">Failed</div><h3>{html.escape(case['title'])}</h3><p>{html.escape(case.get('error','Unknown failure'))}</p></div></article>''')
    summary = data.get("summary", {})
    repro = data.get("reproducibility") or {}
    generation_times = [case.get("timing", {}).get("comfyui_execution_seconds")
                        for case in ok]
    generation_times = [value for value in generation_times if value is not None]
    generation_range = (f"{min(generation_times):.1f}-{max(generation_times):.1f}s"
                        if generation_times else "unknown")
    featured_html = "" if not featured else f'''<video controls preload="metadata" poster="{featured['image']['site_path']}"><source src="{featured['video']['site_path']}" type="video/mp4"></video>'''
    index = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MiniMax H3 on NVIDIA GB10</title><link rel="stylesheet" href="style.css"></head><body><nav><div><span class="brand">H3 <span class="accent">/</span> GB10</span><a href="#results">Results</a><a href="#gallery">Gallery</a><a href="#limits">Limits</a><a href="evidence.html">Evidence</a></div></nav><header class="hero"><div><div class="eyebrow">Single-host capability report</div><h1>MiniMax H3<br>on NVIDIA GB10</h1><p class="lede">Real video generations and native saved frames from one DGX Spark. Every result is linked to its prompt, timing, hash, and runtime evidence.</p><div class="metrics"><div class="metric"><b>{summary.get('successful',0)}/{summary.get('total',0)}</b><span>successful formal runs</span></div><div class="metric"><b>{data.get('selected_profile',{}).get('frames','?')} frames</b><span>trained-range duration profile</span></div><div class="metric"><b>{generation_range}</b><span>ComfyUI execution time range</span></div><div class="metric"><b>{'Yes' if repro.get('decoded_frames_equal') else 'No'}</b><span>decoded-frame repeatability</span></div><div class="metric"><b>{data.get('selected_profile',{}).get('id','unknown')}</b><span>frozen profile</span></div><div class="metric"><b>{data['status'].upper()}</b><span>run status · {data.get('completed_at','')}</span></div></div></div>{featured_html}</header><main><section class="band" id="results"><div class="kicker">Measured outcome</div><h2>A bounded, inspectable run</h2><p class="intro">This report measures one deployed configuration. It records success, timing, media structure, exact hashes, serial stability, and fatal scans; it does not assign a subjective quality score.</p></section><section class="band" id="gallery"><div class="kicker">Generated artifacts</div><h2>Videos and native frames</h2><p class="intro">Poster images were saved from the generated frame tensor by ComfyUI in the same prompt as each video.</p><div class="gallery">{''.join(cards)}</div></section><section class="band" id="limits"><div class="kicker">Interpretation</div><h2>What this run does not prove</h2><div class="limit"><div><h3>No cross-model ranking</h3><p>This is a capability report for one pinned H3 deployment.</p></div><div><h3>No subjective score</h3><p>Visual output is presented for direct inspection without invented quality numbers.</p></div><div><h3>No exact hardware peak</h3><p>Resource values are polling samples, not continuous peak instrumentation.</p></div></div></section></main><footer>Run <span class="hash">{data['run_id']}</span> · <a href="evidence.html">Open full evidence handbook</a></footer></body></html>'''
    rows, details = [], []
    for case in cases:
        timing = case.get("timing", {})
        samples = case.get("resources", [])
        available = [row.get("available_memory_kib") for row in samples
                     if row.get("available_memory_kib") is not None]
        rss = [row.get("comfyui_rss_kib") for row in samples
               if row.get("comfyui_rss_kib") is not None]
        gpu = [row.get("gpu_utilization_percent") for row in samples
               if row.get("gpu_utilization_percent") is not None]
        temperature = [row.get("gpu_temperature_celsius") for row in samples
                       if row.get("gpu_temperature_celsius") is not None]
        power = [row.get("gpu_power_draw_watts") for row in samples
                 if row.get("gpu_power_draw_watts") is not None]
        resource_summary = {
            "polling_samples": len(samples),
            "minimum_available_memory_gib": round(min(available) / 1048576, 2) if available else None,
            "maximum_comfyui_rss_gib": round(max(rss) / 1048576, 2) if rss else None,
            "maximum_sampled_gpu_utilization_percent": max(gpu) if gpu else None,
            "maximum_sampled_gpu_temperature_celsius": max(temperature) if temperature else None,
            "maximum_sampled_gpu_power_draw_watts": max(power) if power else None,
            "interpretation": "bounded polling samples, not exact continuous peaks",
        }
        rows.append(f"<tr><td><a href='#{case['id']}'>{html.escape(case['id'])}</a></td><td>{case['status']}</td><td>{timing.get('bounded_wall_seconds','—')}</td><td>{media_info(case) if case['status']=='success' else '—'}</td></tr>")
        details.append(f'''<details id="{case['id']}"><summary>{html.escape(case['title'])} · {case['status']}</summary><p><b>Prompt:</b> {html.escape(case['prompt'])}</p><pre>{html.escape(json.dumps({**{k:case.get(k) for k in ('seed','profile','timing','error') if k in case},'resource_polling_summary':resource_summary},indent=2))}</pre>{'' if case['status']!='success' else '<p class="hash"><b>Video SHA-256:</b> '+case['video']['sha256']+'<br><b>Decoded RGB sequence:</b> '+case['video']['decoded_rgb_sequence_sha256']+'<br><b>PNG SHA-256:</b> '+case['image']['sha256']+'</p>'}</details>''')
    evidence_json = html.escape(json.dumps({"deployment":data["deployment"],"selected_profile":data.get("selected_profile"),"reproducibility":data.get("reproducibility"),"fatal_scans":data.get("fatal_scans")}, indent=2))
    evidence = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MiniMax H3 Benchmark Evidence</title><link rel="stylesheet" href="style.css"></head><body><nav><div><a class="brand" href="index.html">H3 <span class="accent">/</span> GB10</a><a href="#matrix">Matrix</a><a href="#cases">Cases</a><a href="#reproduce">Reproduce</a></div></nav><main><section class="band"><div class="kicker">Technical handbook</div><h1>Benchmark evidence</h1><p class="intro">Immutable run <span class="hash">{data['run_id']}</span>, completed {data.get('completed_at','unknown')}.</p><pre>{evidence_json}</pre></section><section class="band" id="matrix"><h2>Test matrix</h2><div class="table-wrap"><table><thead><tr><th>Case</th><th>Status</th><th>Bounded wall (s)</th><th>Media</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section><section class="band" id="cases"><h2>Per-case receipts</h2>{''.join(details)}</section><section class="band" id="reproduce"><h2>Reproduce and operate</h2><pre>cd /home/admin/minimax-h3-benchmark
./execution/minimax-h3-benchmark/run-benchmark.sh
./execution/minimax-h3-benchmark/status-report.sh
./execution/minimax-h3-benchmark/restart-report.sh
./execution/minimax-h3-benchmark/stop-report.sh</pre><p>Raw normalized evidence: <a href="benchmark.json">benchmark.json</a>.</p></section></main><footer><a href="index.html">Back to visual report</a></footer></body></html>'''
    (site / "index.html").write_text(index)
    (site / "evidence.html").write_text(evidence)
    for path in site.rglob("*"):
        if path.is_symlink() or (path.is_file() and site not in path.resolve().parents):
            raise RuntimeError("unsafe site artifact")
    print(site)


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    run_parser = subs.add_parser("run")
    run_parser.add_argument("--root", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--workflow", required=True)
    run_parser.add_argument("--cases", required=True)
    run_parser.add_argument("--port", type=int, default=8188)
    render_parser = subs.add_parser("render")
    render_parser.add_argument("--input", required=True)
    render_parser.add_argument("--site", required=True)
    args = parser.parse_args()
    {"run": run, "render": render}[args.command](args)


if __name__ == "__main__":
    main()
