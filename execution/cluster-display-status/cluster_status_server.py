#!/usr/bin/env python3
"""GB10 cluster display status agent.

Read-only collector for the ESP32 touch display, the browser mirror, and the
LAN portal. Serves /status (JSON snapshot), /health, and the static dashboard
mirror. Host metrics come from nvidia-smi, /proc, and /sys on the local head
node and from one batched SSH snapshot on the worker; model metrics come from
the vLLM Prometheus endpoint. Nothing here mutates model containers or
deployment configuration.
"""

import argparse
import glob
import json
import math
import os
import re
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

WORKER = "admin@192.168.88.198"
METRICS_URL = "http://127.0.0.1:8890/metrics"
MODELS_URL = "http://127.0.0.1:8890/v1/models"
MODEL_NAME_TTL_S = 30.0
_served_model_cache = {"name": None, "checked": 0.0}
DASHBOARD_PATH = Path(__file__).with_name("dashboard.html")
PAGE_ROTATION_MS = 10000
CACHE_SECONDS = 2.0
SECTOR_BYTES = 512
# Estimated whole-node draw: GPU board draw + a linear 5.2-65 W CPU model +
# 23 W of memory/network/base overhead, clamped to the DGX Spark envelope.
# This mirrors the sparkDash fleet-energy model and is an estimate, not a
# wall-meter reading; consumers must present it as power_sys_est_w.
CPU_TDP_W = 65.0
CPU_IDLE_W = 5.2
BASE_OVERHEAD_W = 23.0
SYSTEM_DRAW_CLAMP_W = 240.0

# Read-only snapshot gathered over the existing worker SSH channel. Sections
# are separated by --- markers so optional fields cannot shift the parsing.
# /proc/stat, /proc/net/dev, and /proc/diskstats are read twice around a
# 1 s sleep; the two /proc/uptime reads give the exact sample spacing so the
# derived CPU/network/disk rates stay correct under SSH jitter.
WORKER_SNAPSHOT = (
    "nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,power.draw,"
    "clocks.current.sm,clocks.max.sm,"
    "clocks_throttle_reasons.hw_thermal_slowdown,"
    "clocks_throttle_reasons.sw_power_cap --format=csv,noheader,nounits; "
    "echo ---; nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory "
    "--format=csv,noheader,nounits; echo ---; "
    "cat /proc/loadavg; echo ---; cat /proc/meminfo; echo ---; "
    'for h in /sys/class/hwmon/hwmon*; do if [ "$(cat "$h/name" 2>/dev/null)" '
    '= nvme ]; then cat "$h/temp1_input"; fi; done; echo ---; '
    "cat /proc/uptime; echo ---; df -P /; echo ---; "
    "cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null; echo ---; "
    "cat /proc/stat; echo ---; cat /proc/net/dev; echo ---; "
    "cat /proc/diskstats; echo ---; "
    "sleep 1; cat /proc/uptime; echo ---; "
    "cat /proc/stat; echo ---; cat /proc/net/dev; echo ---; cat /proc/diskstats"
)

_cache_lock = threading.Lock()
_cache_time = 0.0
_cache_payload = None
_gather_lock = threading.Lock()
_counter_state = {}
_rate_state = {}

GPU_QUERY_ARGS = (
    "--query-gpu=temperature.gpu,utilization.gpu,power.draw,"
    "clocks.current.sm,clocks.max.sm,"
    "clocks_throttle_reasons.hw_thermal_slowdown,"
    "clocks_throttle_reasons.sw_power_cap",
    "--format=csv,noheader,nounits",
)
COMPUTE_APPS_ARGS = (
    "--query-compute-apps=pid,process_name,used_gpu_memory",
    "--format=csv,noheader,nounits",
)


def rotation_seconds(value):
    seconds = int(value)
    if not 1 <= seconds <= 300:
        raise argparse.ArgumentTypeError("must be between 1 and 300")
    return seconds


def run(command, timeout=3):
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def read_file(path):
    return Path(path).read_text(encoding="ascii", errors="replace")


def parse_gpu_line(line):
    values = [value.strip() for value in line.split(",")]

    def number(index, cast=float):
        if index >= len(values) or values[index] in {"[N/A]", "N/A", ""}:
            return None
        return cast(float(values[index]))

    def flag(index):
        if index >= len(values):
            return None
        return values[index] == "Active"

    return {
        "temp_c": number(0, int),
        "gpu_util_pct": number(1, int),
        "power_w": number(2),
        "sm_clock_mhz": number(3, int),
        "sm_clock_max_mhz": number(4, int),
        "throttle_thermal": flag(5),
        "throttle_power_cap": flag(6),
    }


def parse_compute_apps_mb(text):
    """GPU-allocated memory: the only working source on the GB10 unified pool."""
    total = 0
    for line in text.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 3 or not fields[0]:
            continue
        try:
            total += int(float(fields[2]))
        except ValueError:
            continue
    return total


def parse_meminfo(meminfo):
    fields = {}
    for line in meminfo.splitlines():
        match = re.match(r"(MemTotal|MemAvailable):\s+(\d+)", line)
        if match:
            fields[match.group(1)] = int(match.group(2))
    total_kb = fields.get("MemTotal", 0)
    avail_kb = fields.get("MemAvailable", 0)
    if not total_kb:
        return None, None, None
    return (
        round((total_kb - avail_kb) * 100.0 / total_kb, 1),
        round(total_kb / 1024),
        round(avail_kb / 1024),
    )


def parse_nvme_temp_c(text):
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                return round(int(line) / 1000.0)
            except ValueError:
                continue
    return None


def read_nvme_hwmon_temp_c():
    """Composite NVMe temperature from the world-readable hwmon interface."""
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            name = Path(hwmon, "name").read_text(encoding="ascii").strip()
            if name != "nvme":
                continue
            milli = int(Path(hwmon, "temp1_input").read_text(encoding="ascii").strip())
            return round(milli / 1000.0)
        except (OSError, ValueError):
            continue
    return None


def parse_zone_max_c(text):
    """Hottest ACPI thermal zone; on GB10 these track the SoC package."""
    hottest = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            milli = int(line)
        except ValueError:
            continue
        if 0 < milli < 120000:
            celsius = milli / 1000.0
            if hottest is None or celsius > hottest:
                hottest = celsius
    return round(hottest) if hottest is not None else None


def read_zone_max_c():
    try:
        zones = []
        for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            try:
                zones.append(Path(zone, "temp").read_text(encoding="ascii").strip())
            except OSError:
                continue
        return parse_zone_max_c("\n".join(zones))
    except OSError:
        return None


def parse_root_used_pct(df_output):
    lines = [line for line in df_output.splitlines() if line.strip()]
    if not lines:
        return None
    fields = lines[-1].split()
    if len(fields) < 5 or not fields[4].endswith("%"):
        return None
    try:
        return int(fields[4].rstrip("%"))
    except ValueError:
        return None


def local_root_used_pct():
    stat = os.statvfs("/")
    if not stat.f_blocks:
        return None
    return round((stat.f_blocks - stat.f_bavail) * 100.0 / stat.f_blocks)


def parse_proc_stat(text):
    for line in text.splitlines():
        if line.startswith("cpu "):
            fields = [int(field) for field in line.split()[1:10]]
            idle = fields[3] + fields[4]
            return sum(fields), sum(fields) - idle
    return None


def parse_net_dev(text):
    """Aggregate byte counters across physical interfaces only."""
    rx = tx = 0
    for line in text.splitlines():
        match = re.match(
            r"\s*(\S+):\s+(\d+)(?:\s+\d+){7}\s+(\d+)", line
        )
        if not match:
            continue
        name = match.group(1)
        if name == "lo" or not re.match(r"^(en|eth|wl|ww)", name):
            continue
        rx += int(match.group(2))
        tx += int(match.group(3))
    return rx, tx


def parse_diskstats(text):
    """Aggregate sector counters across NVMe namespace devices."""
    sectors_read = sectors_written = 0
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 10 or not re.match(r"^nvme\d+n\d+$", fields[2]):
            continue
        sectors_read += int(fields[5])
        sectors_written += int(fields[9])
    return sectors_read, sectors_written


def apply_system_power_estimate(host):
    draw = host.get("power_w")
    usage = host.get("cpu_usage_pct")
    if draw is None:
        host["power_sys_est_w"] = None
        return
    watts = draw + BASE_OVERHEAD_W
    if usage is not None:
        watts += CPU_IDLE_W + (CPU_TDP_W - CPU_IDLE_W) * max(0.0, min(usage, 100.0)) / 100.0
    host["power_sys_est_w"] = round(min(watts, SYSTEM_DRAW_CLAMP_W), 1)


def local_host(now):
    host = {}
    gpu_line = run(["nvidia-smi", *GPU_QUERY_ARGS]).splitlines()[0]
    host.update(parse_gpu_line(gpu_line))
    host["gpu_mem_mb"] = parse_compute_apps_mb(run(["nvidia-smi", *COMPUTE_APPS_ARGS]))
    host["load1"] = float(read_file("/proc/loadavg").split()[0])
    used_pct, total_mb, avail_mb = parse_meminfo(read_file("/proc/meminfo"))
    host["mem_used_pct"] = used_pct
    host["mem_total_mb"] = total_mb
    host["mem_avail_mb"] = avail_mb
    host["nvme_temp_c"] = read_nvme_hwmon_temp_c()
    host["root_used_pct"] = local_root_used_pct()
    host["cpu_temp_c"] = read_zone_max_c()
    host["uptime_s"] = int(float(read_file("/proc/uptime").split()[0]))

    stat_now = parse_proc_stat(read_file("/proc/stat"))
    net_now = parse_net_dev(read_file("/proc/net/dev"))
    disk_now = parse_diskstats(read_file("/proc/diskstats"))
    previous = dict(_rate_state)
    _rate_state.update(
        {"ts": now, "stat": stat_now, "net": net_now, "disk": disk_now}
    )
    elapsed = now - previous["ts"] if previous else 0.0
    host["cpu_usage_pct"] = None
    host["net_rx_kbps"] = host["net_tx_kbps"] = None
    host["disk_read_kbps"] = host["disk_write_kbps"] = None
    if previous and elapsed > 0:
        if previous["stat"] and stat_now:
            total_delta = stat_now[0] - previous["stat"][0]
            used_delta = stat_now[1] - previous["stat"][1]
            if total_delta > 0 and used_delta >= 0:
                host["cpu_usage_pct"] = round(used_delta * 100.0 / total_delta, 1)
        if previous["net"] and net_now:
            rx_delta = net_now[0] - previous["net"][0]
            tx_delta = net_now[1] - previous["net"][1]
            if rx_delta >= 0:
                host["net_rx_kbps"] = round(rx_delta / 1024.0 / elapsed, 1)
            if tx_delta >= 0:
                host["net_tx_kbps"] = round(tx_delta / 1024.0 / elapsed, 1)
        if previous["disk"] and disk_now:
            read_delta = disk_now[0] - previous["disk"][0]
            write_delta = disk_now[1] - previous["disk"][1]
            if read_delta >= 0:
                host["disk_read_kbps"] = round(
                    read_delta * SECTOR_BYTES / 1024.0 / elapsed, 1
                )
            if write_delta >= 0:
                host["disk_write_kbps"] = round(
                    write_delta * SECTOR_BYTES / 1024.0 / elapsed, 1
                )
    apply_system_power_estimate(host)
    return host


def worker_host(now=0.0):
    """Worker snapshot over SSH; now is unused (rates come from in-snapshot samples)."""
    output = run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=2", WORKER, WORKER_SNAPSHOT],
        timeout=8,
    )
    sections = output.split("---")
    if len(sections) < 15:
        raise ValueError(f"unexpected worker snapshot: {output[:80]!r}")
    host = parse_gpu_line(sections[0].splitlines()[0])
    host["gpu_mem_mb"] = parse_compute_apps_mb(sections[1])
    host["load1"] = float(sections[2].split()[0])
    used_pct, total_mb, avail_mb = parse_meminfo(sections[3])
    host["mem_used_pct"] = used_pct
    host["mem_total_mb"] = total_mb
    host["mem_avail_mb"] = avail_mb
    host["nvme_temp_c"] = parse_nvme_temp_c(sections[4])
    uptime_start = float(sections[5].split()[0])
    host["uptime_s"] = int(uptime_start)
    host["root_used_pct"] = parse_root_used_pct(sections[6])
    host["cpu_temp_c"] = parse_zone_max_c(sections[7])

    stat_start = parse_proc_stat(sections[8])
    net_start = parse_net_dev(sections[9])
    disk_start = parse_diskstats(sections[10])
    elapsed = max(float(sections[11].split()[0]) - uptime_start, 0.0)
    stat_end = parse_proc_stat(sections[12])
    net_end = parse_net_dev(sections[13])
    disk_end = parse_diskstats(sections[14])

    host["cpu_usage_pct"] = None
    host["net_rx_kbps"] = host["net_tx_kbps"] = None
    host["disk_read_kbps"] = host["disk_write_kbps"] = None
    if elapsed > 0:
        if stat_start and stat_end:
            total_delta = stat_end[0] - stat_start[0]
            used_delta = stat_end[1] - stat_start[1]
            if total_delta > 0 and used_delta >= 0:
                host["cpu_usage_pct"] = round(used_delta * 100.0 / total_delta, 1)
        if net_start and net_end:
            rx_delta = net_end[0] - net_start[0]
            tx_delta = net_end[1] - net_start[1]
            if rx_delta >= 0:
                host["net_rx_kbps"] = round(rx_delta / 1024.0 / elapsed, 1)
            if tx_delta >= 0:
                host["net_tx_kbps"] = round(tx_delta / 1024.0 / elapsed, 1)
        if disk_start and disk_end:
            read_delta = disk_end[0] - disk_start[0]
            write_delta = disk_end[1] - disk_start[1]
            if read_delta >= 0:
                host["disk_read_kbps"] = round(
                    read_delta * SECTOR_BYTES / 1024.0 / elapsed, 1
                )
            if write_delta >= 0:
                host["disk_write_kbps"] = round(
                    write_delta * SECTOR_BYTES / 1024.0 / elapsed, 1
                )
    apply_system_power_estimate(host)
    return host


def metric_value(text, name):
    pattern = rf"^{re.escape(name)}(?:\{{[^}}]*\}})?\s+([-+0-9.eE]+)$"
    total = 0.0
    found = False
    for line in text.splitlines():
        match = re.match(pattern, line)
        if match:
            total += float(match.group(1))
            found = True
    return total if found else None


def histogram_quantile(text, name, quantile):
    """Smallest bucket upper bound covering the quantile; +Inf collapses to None."""
    pattern = rf"^{re.escape(name)}\{{[^}}]*le=\"([^\"]+)\"[^}}]*\}}\s+([-+0-9.eE]+)$"
    buckets = []
    for line in text.splitlines():
        match = re.match(pattern, line)
        if not match:
            continue
        try:
            bound = float(match.group(1))
            count = float(match.group(2))
        except ValueError:
            continue
        buckets.append((bound, count))
    if not buckets:
        return None
    buckets.sort()
    total = buckets[-1][1]
    if total <= 0:
        return None
    threshold = quantile * total
    for bound, count in buckets:
        if count >= threshold:
            return bound if math.isfinite(bound) else None
    return None


def window_mean_ms(text, base, now):
    """Recent-window mean latency from histogram sum/count deltas, in ms.

    Falls back to the cumulative mean while the recent window has no finished
    requests, so an idle service still reports a useful last-known latency.
    """
    total_sum = metric_value(text, f"{base}_sum")
    total_count = metric_value(text, f"{base}_count")
    if total_sum is None or total_count is None:
        return None
    previous = _counter_state.get(base)
    _counter_state[base] = (total_sum, total_count, now)
    if (
        previous
        and total_sum >= previous[0]
        and total_count > previous[1]
        and now > previous[2]
    ):
        mean_seconds = (total_sum - previous[0]) / (total_count - previous[1])
    elif total_count > 0:
        mean_seconds = total_sum / total_count
    else:
        return None
    return round(mean_seconds * 1000.0, 1)


def to_ms(seconds):
    if seconds is None or not math.isfinite(seconds):
        return None
    return round(seconds * 1000.0, 1)


def ratio_pct(numerator, denominator):
    if numerator is None or not denominator:
        return None
    return round(numerator * 100.0 / denominator, 1)


def counter_rate(name, value, now):
    previous = _counter_state.get(name)
    _counter_state[name] = (value, now)
    if previous is None or value < previous[0] or now <= previous[1]:
        return 0.0
    return round((value - previous[0]) / (now - previous[1]), 1)



def served_model_name(now):
    """Auto-discover the served model id from the upstream /v1/models endpoint."""
    cache = _served_model_cache
    if cache["name"] and (now - cache["checked"]) < MODEL_NAME_TTL_S:
        return cache["name"]
    try:
        with urllib.request.urlopen(MODELS_URL, timeout=2) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        if ids:
            cache["name"] = ids[0]
            cache["checked"] = now
            return cache["name"]
    except Exception:
        pass
    return cache["name"] or "unavailable"

def model_status(now):
    try:
        with urllib.request.urlopen(METRICS_URL, timeout=2) as response:
            metrics = response.read().decode("utf-8", errors="replace")
        running = int(metric_value(metrics, "vllm:num_requests_running") or 0)
        waiting = int(metric_value(metrics, "vllm:num_requests_waiting") or 0)
        kv = metric_value(metrics, "vllm:kv_cache_usage_perc") or 0.0
        prompt_total = metric_value(metrics, "vllm:prompt_tokens_total") or 0.0
        generation_total = metric_value(metrics, "vllm:generation_tokens_total") or 0.0
        prefix_hits = metric_value(metrics, "vllm:prefix_cache_hits_total")
        prefix_queries = metric_value(metrics, "vllm:prefix_cache_queries_total")
        accepted = metric_value(metrics, "vllm:spec_decode_num_accepted_tokens_total")
        drafted = metric_value(metrics, "vllm:spec_decode_num_draft_tokens_total")
        return {
            "healthy": True,
            "name": served_model_name(now),
            "running": running,
            "waiting": waiting,
            "kv_pct": round(kv * 100.0, 1),
            "prompt_tps": counter_rate("prompt", prompt_total, now),
            "generation_tps": counter_rate("generation", generation_total, now),
            "ttft_ms": window_mean_ms(
                metrics, "vllm:time_to_first_token_seconds", now
            ),
            "ttft_p95_ms": to_ms(
                histogram_quantile(metrics, "vllm:time_to_first_token_seconds_bucket", 0.95)
            ),
            "itl_p95_ms": to_ms(
                histogram_quantile(metrics, "vllm:inter_token_latency_seconds_bucket", 0.95)
            ),
            "preemptions_total": int(metric_value(metrics, "vllm:num_preemptions_total") or 0),
            "prefix_cache_hit_pct": ratio_pct(prefix_hits, prefix_queries),
            "spec_accept_pct": ratio_pct(accepted, drafted),
        }
    except Exception as error:
        return {
            "healthy": False,
            "name": served_model_name(now),
            "running": 0,
            "waiting": 0,
            "kv_pct": 0.0,
            "prompt_tps": 0.0,
            "generation_tps": 0.0,
            "ttft_ms": None,
            "ttft_p95_ms": None,
            "itl_p95_ms": None,
            "preemptions_total": 0,
            "prefix_cache_hit_pct": None,
            "spec_accept_pct": None,
            "error": str(error),
        }


def gather(now):
    payload = {
        "updated": time.strftime("%H:%M:%S"),
        "page_rotation_ms": PAGE_ROTATION_MS,
        "head": None,
        "worker": None,
        "model": model_status(now),
    }
    errors = []
    for key, collector in (("head", local_host), ("worker", worker_host)):
        try:
            payload[key] = collector(now)
        except Exception as error:
            errors.append(f"{key}: {error}")
    if errors:
        payload["errors"] = errors
    return payload


def collect():
    """Return a cached snapshot no older than CACHE_SECONDS.

    Gathering happens outside the cache lock so slow sources (the worker SSH
    snapshot sleeps ~1 s) cannot serialize concurrent readers; a single gather
    lock keeps rate baselines single-writer, and stale data is served while a
    refresh is already in flight.
    """
    global _cache_payload, _cache_time
    now = time.time()
    with _cache_lock:
        if _cache_payload is not None and now - _cache_time < CACHE_SECONDS:
            return _cache_payload
    if not _gather_lock.acquire(blocking=False):
        with _cache_lock:
            if _cache_payload is not None:
                return _cache_payload
        return {
            "updated": time.strftime("%H:%M:%S"),
            "page_rotation_ms": PAGE_ROTATION_MS,
            "head": None,
            "worker": None,
            "model": {"healthy": False, "name": served_model_name(now), "error": "refresh in progress"},
        }
    try:
        payload = gather(now)
        with _cache_lock:
            _cache_payload = payload
            _cache_time = time.time()
        return payload
    finally:
        _gather_lock.release()


class Handler(BaseHTTPRequestHandler):
    def send_headers(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

    def send_body(self, body, content_type):
        self.send_headers(body, content_type)
        self.wfile.write(body)

    def do_HEAD(self):
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            try:
                body = DASHBOARD_PATH.read_bytes()
            except OSError:
                self.send_error(503, "Dashboard unavailable")
                return
            self.send_headers(body, "text/html; charset=utf-8")
            return
        if path == "/health":
            body = b'{"ok":true}'
            self.send_headers(body, "application/json")
            return
        self.send_error(404)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            try:
                body = DASHBOARD_PATH.read_bytes()
            except OSError:
                self.send_error(503, "Dashboard unavailable")
                return
            self.send_body(body, "text/html; charset=utf-8")
            return
        if path not in {"/status", "/health"}:
            self.send_error(404)
            return
        payload = collect() if path == "/status" else {"ok": True}
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_body(body, "application/json")

    def log_message(self, fmt, *args):
        return


def main():
    global PAGE_ROTATION_MS
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9108)
    parser.add_argument(
        "--page-rotation-seconds",
        type=rotation_seconds,
        default=10,
        metavar="SECONDS",
        help="dashboard page rotation interval from 1 to 300 seconds (default: 10)",
    )
    args = parser.parse_args()
    PAGE_ROTATION_MS = args.page_rotation_seconds * 1000
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
