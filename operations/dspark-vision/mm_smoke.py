import base64, json, struct, sys, time, urllib.request, zlib, random

def png(w, h, seed=7):
    rnd = random.Random(seed)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(((x * 7 + y * 3 + rnd.randrange(64)) & 255,
                          (x ^ y) & 255,
                          (rnd.randrange(256)) if (x // 64 + y // 64) % 2 else 200))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))

w, h = int(sys.argv[1]), int(sys.argv[2])
img = base64.b64encode(png(w, h)).decode()
body = {"model": "deepseek-v4-flash-0731", "max_tokens": 64, "temperature": 0,
        "chat_template_kwargs": {"thinking": False},
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img}},
            {"type": "text", "text": "Describe this image in one short sentence."}]}]}
t0 = time.time()
req = urllib.request.Request("http://127.0.0.1:8890/v1/chat/completions",
                             data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
        print("HTTP", r.status, "%.1fs" % (time.time() - t0), "usage=", d.get("usage"))
        print("content:", (d["choices"][0]["message"].get("content") or "")[:200].replace("\n", " "))
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read()[:500]); sys.exit(1)
