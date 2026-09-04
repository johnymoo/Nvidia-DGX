#!/usr/bin/env python3
"""Prompt generators for the eval suite blocks (S/M/L/N/C/T/V).

Random-word bodies and the 3.54 tok/word calibration are lifted from
`execution/kv-offload-d0/d0_probes.py::rand_words`. The needle-marker pattern
(a unique token buried mid-body, asked to be quoted back exactly) is lifted
from `execution/kv-offload-phase-b/b2_probe.py`. The menu-image quality probe
reuses `execution/benchmarks/vision_compare.py` (prompt, response schema,
47-field grader) through an optional by-path import -- that file is
import-safe (constants and functions only, guarded `__main__`) but is not
part of this package (customer-derived), so `vision_compare()` returns None
when it is absent and block V records a skip. The synthetic placeholder PNG
is generated in-package by `_png` (byte-identical to that module's `png`).
"""
from __future__ import annotations

import binascii
import importlib.util
import random
import string
import struct
import zlib
from pathlib import Path
from types import ModuleType

TOK_PER_WORD = 3.54  # calibrated on random-lowercase-word bodies (d0_probes A1 campaign)
NATURAL_PROSE_TOK_PER_WORD = 1.3  # rough BPE guide for real English prose; not calibrated


def rand_words(n_words: int, seed: int) -> str:
    rng = random.Random(seed)
    words = []
    for _ in range(n_words):
        w = "".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 9)))
        words.append(w)
    return " ".join(words)


def tokens_to_words(n_tokens: int) -> int:
    return max(1, round(n_tokens / TOK_PER_WORD))


def estimate_tokens_natural(text: str) -> int:
    """Rough word-count-based estimate for manifest/dry-run display only."""
    return round(len(text.split()) * NATURAL_PROSE_TOK_PER_WORD)


def make_marker(seed: int) -> str:
    letters = "".join(random.Random(seed ^ 0xA5A5).choices(string.ascii_uppercase, k=4))
    return f"NEEDLE-{seed}-{letters}"


def build_random_body(n_tokens: int, seed: int) -> str:
    return rand_words(tokens_to_words(n_tokens), seed)


def build_needle_body(n_tokens: int, seed: int, marker: str, frac: float = 0.5) -> str:
    words = rand_words(tokens_to_words(n_tokens), seed).split()
    idx = min(len(words) - 1, max(0, int(len(words) * frac)))
    words[idx] = marker
    return " ".join(words)


NEEDLE_QUESTION = (
    "\n\nA unique identifier token is buried in the text above. Reply with "
    "ONLY that identifier token and nothing else."
)
SUMMARY_QUESTION = "\n\nSummarize the text above in exactly one sentence."
ONE_WORD_QUESTION = "\n\nSummarize the text above in one word."


# --- Block S: short natural-prose chat -------------------------------------
# Word counts are sized to land roughly in the 200-900 token range at
# NATURAL_PROSE_TOK_PER_WORD; real prompt_tokens usage is authoritative and
# recorded per-sample, this is only for the dry-run/manifest estimate.
SHORT_CHAT_PROMPTS: tuple[str, ...] = (
    "Explain the difference between optimistic and pessimistic locking in a "
    "relational database, and give one example of a workload where each "
    "approach wins.",
    "Here is a Python function that intermittently returns stale data from a "
    "cache:\n\n"
    "```python\n"
    "def get_user(user_id):\n"
    "    cached = CACHE.get(user_id)\n"
    "    if cached:\n"
    "        return cached\n"
    "    user = db.query(User).filter_by(id=user_id).first()\n"
    "    CACHE.set(user_id, user, ttl=3600)\n"
    "    return user\n"
    "```\n\n"
    "List the most likely causes of staleness here and how you would fix "
    "each one, in order of how often you'd expect to see them in "
    "production.",
    "Summarize the following incident report in three bullet points aimed "
    "at an on-call engineer who has thirty seconds to read it: at 02:14 UTC "
    "the payments service began returning 502s to roughly 12% of requests; "
    "the on-call engineer found that a downstream currency-conversion "
    "dependency had started timing out after a certificate rotation "
    "changed its TLS handshake latency; a temporary mitigation raised the "
    "client timeout from 200ms to 800ms, which resolved the immediate "
    "issue but increased P99 latency for all payment requests by roughly "
    "150ms until the certificate issue was root-caused and fixed at 04:40 "
    "UTC.",
    "Draft a short, polite email to a vendor asking them to extend a "
    "software license renewal deadline by two weeks because the "
    "internal budget approval is delayed, while making clear we intend "
    "to renew and don't want the license to lapse in the meantime.",
    "Review this code for correctness and efficiency issues:\n\n"
    "```python\n"
    "def dedupe_preserve_order(items):\n"
    "    result = []\n"
    "    for item in items:\n"
    "        if item not in result:\n"
    "            result.append(item)\n"
    "    return result\n"
    "\n"
    "def merge_intervals(intervals):\n"
    "    intervals.sort()\n"
    "    merged = [intervals[0]]\n"
    "    for start, end in intervals[1:]:\n"
    "        if start <= merged[-1][1]:\n"
    "            merged[-1] = (merged[-1][0], max(merged[-1][1], end))\n"
    "        else:\n"
    "            merged.append((start, end))\n"
    "    return merged\n"
    "```\n\n"
    "Point out any bugs, quadratic-time hot spots, and edge cases (empty "
    "input, single interval) that aren't handled, and suggest concrete "
    "fixes for each.",
    "A team is deciding between polling a job-status endpoint every 5 "
    "seconds versus opening a long-lived websocket connection for a "
    "dashboard that tracks about 200 concurrent background jobs per "
    "customer, across roughly 40 customers. Walk through the tradeoffs "
    "in server load, latency to see a status change, and operational "
    "complexity, and give a recommendation with your reasoning.",
    "Here is the relevant section of a `docker-compose.yml` file:\n\n"
    "```yaml\n"
    "services:\n"
    "  api:\n"
    "    image: myco/api:latest\n"
    "    restart: unless-stopped\n"
    "    environment:\n"
    "      - DATABASE_URL=postgres://app:app@db:5432/app\n"
    "      - REDIS_URL=redis://cache:6379/0\n"
    "    depends_on:\n"
    "      - db\n"
    "      - cache\n"
    "    ports:\n"
    "      - \"8080:8080\"\n"
    "  db:\n"
    "    image: postgres:16\n"
    "    volumes:\n"
    "      - dbdata:/var/lib/postgresql/data\n"
    "  cache:\n"
    "    image: redis:7\n"
    "volumes:\n"
    "  dbdata:\n"
    "```\n\n"
    "Explain what happens, in order, if the `db` container is slow to "
    "accept connections on a fresh boot, and what `depends_on` does and "
    "does not guarantee here. Suggest one concrete change to make startup "
    "more robust.",
    "Rewrite the following paragraph to be clearer and about half the "
    "length, keeping all the factual content: \"In terms of the way that "
    "the system handles requests when there is a lot of load on it, what "
    "basically happens is that once the number of requests that are "
    "currently being processed at the same time gets to be higher than "
    "a certain configured threshold value, any new requests that come in "
    "after that point will not be processed right away, but will instead "
    "be placed into a queue, and they will wait there until there is "
    "enough capacity freed up by other requests finishing, at which point "
    "they will then start being processed in roughly the order they "
    "arrived in, although this order is not strictly guaranteed in all "
    "cases.\"",
)
assert len(SHORT_CHAT_PROMPTS) == 8


# --- Block T: tool calls -----------------------------------------------------
TOOLS: tuple[dict, ...] = (
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City and country, e.g. 'Boston, US'"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command on the host and return its stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "The shell command to execute"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute or relative file path"}},
                "required": ["path"],
            },
        },
    },
)

TOOL_PROMPTS: tuple[str, ...] = (
    "What's the weather like in Boston right now?",
    "Run `ls -la /tmp` and tell me what files are there.",
    "Read the file at /etc/hosts and summarize its contents.",
    "I need today's weather in Tokyo, in Celsius please.",
    "Execute `df -h` and report which filesystem is most full.",
    "Open /var/log/syslog and check the last few lines for errors.",
)
assert len(TOOL_PROMPTS) == 6


# --- Block V: vision (menu image) -------------------------------------------
_VISION_COMPARE_PATH = Path(__file__).resolve().parent.parent / "benchmarks" / "vision_compare.py"
_vision_compare_module: ModuleType | None = None


def vision_compare() -> ModuleType | None:
    """Lazily import execution/benchmarks/vision_compare.py by path (it has
    no package __init__.py, so a plain `import` would not find it). Returns
    None when the file is absent: the menu grader and its 47-field truth are
    customer-derived and deliberately not committed with this package."""
    if not _VISION_COMPARE_PATH.is_file():
        return None
    global _vision_compare_module
    if _vision_compare_module is None:
        spec = importlib.util.spec_from_file_location("vision_compare", _VISION_COMPARE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _vision_compare_module = module
    return _vision_compare_module


def _png(width: int, height: int, rectangles: list[tuple[int, int, int, int, tuple[int, int, int]]]) -> bytes:
    # byte-identical to vision_compare.py::png with marker=0; inlined so the
    # placeholder image needs no out-of-package file
    background = bytes((245, 245, 245))
    rows = [bytearray(background * width) for _ in range(height)]
    for x0, y0, x1, y1, color in rectangles:
        pixel = bytes(color)
        for y in range(max(0, y0), min(height, y1)):
            rows[y][max(0, x0) * 3 : min(width, x1) * 3] = pixel * max(0, min(width, x1) - max(0, x0))
    rows[-1][-3:] = bytes((0, 0, 0))
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = binascii.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def load_menu_image(path: Path | None) -> bytes:
    """Real runs pass EVAL_MENU_IMAGE (the actual menu photo; not committed
    to this repo). Offline tests have no such photo, so fall back to a
    synthetic placeholder PNG from _png() -- the mock server does not look
    at pixel content, only the grader does, and the grader is exercised
    separately against MENU_TRUTH in the tests."""
    if path is not None:
        return path.read_bytes()
    return _png(160, 120, [(0, 0, 160, 120, (245, 245, 245))])
