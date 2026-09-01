#!/usr/bin/env python3
"""ZMQ subscriber for vLLM KV cache events (D0 diagnostic arm).

Runs wherever pyzmq + network reachability exist. Preferred: INSIDE the engine
container (guaranteed pyzmq; engine publishes on 127.0.0.1:19555 and the
service uses network_mode: host):

    docker cp kv_events_subscriber.py gb10-deepseek-v4-vllm-dspark-1:/tmp/
    docker exec -d gb10-deepseek-v4-vllm-dspark-1 \
      python3 /tmp/kv_events_subscriber.py --out /tmp/kv_events_d0.jsonl
    # stop:
    docker exec gb10-deepseek-v4-vllm-dspark-1 touch /tmp/kv_sub_stop
    docker cp gb10-deepseek-v4-vllm-dspark-1:/tmp/kv_events_d0.jsonl .

Every received message is written as one JSON line:
    {"recv_ts": <epoch>, "frames": N, "topic": ..., "payload": <parsed json or raw string>}
Batch wrappers ({"events": [...]}) are NOT flattened here — analyze_d0.py does
that, so the raw stream stays the evidence record. Unknown/binary frames are
kept as utf-8 replacement strings.
"""
import argparse
import json
import os
import signal
import time

import zmq

_stop = False


def _handle(signum, frame):
    global _stop
    _stop = True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", default="tcp://127.0.0.1:19555")
    p.add_argument("--topic", default="kv")
    p.add_argument("--out", required=True)
    p.add_argument("--stop-flag", default="/tmp/kv_sub_stop")
    p.add_argument("--max-seconds", type=float, default=3600.0)
    a = p.parse_args()

    if a.stop_flag and os.path.exists(a.stop_flag):
        os.remove(a.stop_flag)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.RCVHWM, 0)  # unlimited receive buffer: never drop evidence
    sub.setsockopt_string(zmq.SUBSCRIBE, a.topic)
    sub.connect(a.endpoint)

    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    n_msgs = 0
    n_bytes = 0
    deadline = time.time() + a.max_seconds
    with open(a.out, "w", buffering=1, encoding="utf-8") as f:
        while not _stop and time.time() < deadline:
            if a.stop_flag and os.path.exists(a.stop_flag):
                break
            socks = dict(poller.poll(timeout=200))
            if sub not in socks:
                continue
            try:
                parts = sub.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                continue
            n_msgs += 1
            payload = None
            topic = None
            for part in parts:
                n_bytes += len(part)
                try:
                    text = part.decode("utf-8")
                except UnicodeDecodeError:
                    text = part.decode("utf-8", errors="replace")
                if topic is None and text.startswith(a.topic):
                    topic = text
                    continue
                try:
                    parsed = json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    parsed = text
                payload = parsed if payload is None else [payload, parsed]
            f.write(json.dumps({"recv_ts": round(time.time(), 3), "frames": len(parts), "topic": topic, "payload": payload}) + "\n")

    if _stop:
        reason = "signal"
    elif a.stop_flag and os.path.exists(a.stop_flag):
        reason = "flag"
    else:
        reason = "deadline"
    print(json.dumps({"messages": n_msgs, "bytes": n_bytes, "out": a.out, "stopped_by": reason}))


if __name__ == "__main__":
    main()
