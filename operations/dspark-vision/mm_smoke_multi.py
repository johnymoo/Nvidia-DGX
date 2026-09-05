"""Multi-image smoke for the DSpark Vision-Exp endpoint.

Usage: python3 mm_smoke_multi.py N [W H] [--single-turn]

Sends N generated PNGs (default 512x384, distinct content) through
/v1/chat/completions. Default layout mimics an agent session: N user turns each
carrying one image, with short assistant replies in between, then a final user
question - i.e. images accumulate across the whole prompt, which is what
--limit-mm-per-prompt counts. --single-turn puts all N images in one user turn.
Exit 0 on HTTP 200, 1 otherwise (prints the error body, useful for probing the cap).
"""
import base64, json, struct, sys, time, urllib.request, zlib, random


def png(w, h, seed):
    rnd = random.Random(seed)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(((x * 7 + y * 3 + rnd.randrange(64)) & 255,
                          (x ^ y ^ seed) & 255,
                          (rnd.randrange(256)) if (x // 64 + y // 64) % 2 else (200 - seed) & 255))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


args = [a for a in sys.argv[1:] if not a.startswith("--")]
single_turn = "--single-turn" in sys.argv
n = int(args[0])
w = int(args[1]) if len(args) > 1 else 512
h = int(args[2]) if len(args) > 2 else 384


def image_part(i):
    data = base64.b64encode(png(w, h, seed=i + 1)).decode()
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + data}}


if single_turn:
    messages = [{"role": "user", "content": [image_part(i) for i in range(n)]
                 + [{"type": "text", "text": f"There are {n} images. Reply with the count only."}]}]
else:
    messages = []
    for i in range(n):
        messages.append({"role": "user", "content": [image_part(i),
                         {"type": "text", "text": f"Screenshot {i + 1}."}]})
        if i < n - 1:
            messages.append({"role": "assistant", "content": f"Noted screenshot {i + 1}."})
    messages[-1]["content"].append({"type": "text",
                                    "text": "How many screenshots have I sent in total? Reply with the number only."})

body = {"model": "deepseek-v4-flash-0731", "max_tokens": 32, "temperature": 0,
        "chat_template_kwargs": {"thinking": False}, "messages": messages}
t0 = time.time()
req = urllib.request.Request("http://127.0.0.1:8890/v1/chat/completions",
                             data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
        print(f"HTTP {r.status} n={n} {w}x{h} {'single' if single_turn else 'multi'}-turn "
              f"{time.time() - t0:.1f}s usage={d.get('usage')}")
        print("content:", (d["choices"][0]["message"].get("content") or "")[:200].replace("\n", " "))
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code} n={n}", e.read()[:400].decode(errors="replace"))
    sys.exit(1)
