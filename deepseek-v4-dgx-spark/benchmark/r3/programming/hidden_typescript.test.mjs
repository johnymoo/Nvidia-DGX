import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const workspace = process.env.R3_PROGRAMMING_WORKSPACE;
const taskId = process.env.R3_PROGRAMMING_TASK_ID;
const modules = {
  "typescript-config-merge": "config_merge.ts",
  "typescript-event-emitter": "event_emitter.ts",
  "typescript-url-router": "url_router.ts",
  "typescript-promise-pool": "promise_pool.ts",
  "typescript-lru-ttl": "lru_ttl.ts",
};

if (!workspace || !modules[taskId]) {
  throw new Error("R3 programming workspace or task ID is missing");
}

const modulePath = join(workspace, modules[taskId]);
const source = await readFile(modulePath, "utf8");
const implementation = await import(pathToFileURL(modulePath).href);

function expectDeclaration(pattern, label) {
  assert.match(source, pattern, `missing exported TypeScript declaration: ${label}`);
}

if (taskId === "typescript-config-merge") {
  test("deep merge copies nested values and defines array and undefined behavior", () => {
    expectDeclaration(/export\s+interface\s+MergeOptions\b/, "MergeOptions");
    expectDeclaration(/export\s+function\s+mergeConfig\s*</, "generic mergeConfig");
    const base = { nested: { port: 8080 }, items: [{ base: true }], keep: { value: 1 } };
    const override = { nested: { host: "localhost" }, items: [{ override: true }], keep: undefined, absent: undefined };
    const result = implementation.mergeConfig(base, override);
    assert.deepEqual(result, {
      nested: { port: 8080, host: "localhost" },
      items: [{ override: true }],
      keep: { value: 1 },
    });
    result.nested.port = 9090;
    result.items[0].override = false;
    assert.deepEqual(base, { nested: { port: 8080 }, items: [{ base: true }], keep: { value: 1 } });
    assert.deepEqual(override, { nested: { host: "localhost" }, items: [{ override: true }], keep: undefined, absent: undefined });
    assert.deepEqual(
      implementation.mergeConfig({ list: [1] }, { list: [2] }, { array: "concat" }),
      { list: [1, 2] },
    );
    const overwritten = implementation.mergeConfig({ value: 1 }, { value: undefined }, { undefined: "overwrite" });
    assert.equal(Object.hasOwn(overwritten, "value"), true);
    assert.equal(overwritten.value, undefined);
  });
}

if (taskId === "typescript-event-emitter") {
  test("once, off, and reentrant emission honor registration snapshots", () => {
    expectDeclaration(/export\s+type\s+EventMap\b/, "EventMap");
    expectDeclaration(/export\s+class\s+TypedEventEmitter\s*</, "generic TypedEventEmitter");
    const emitter = new implementation.TypedEventEmitter();
    const seen = [];
    const second = () => seen.push("second");
    emitter.on("event", () => {
      seen.push("first");
      emitter.off("event", second);
      emitter.on("event", () => seen.push("late"));
    });
    emitter.on("event", second);
    emitter.once("event", () => {
      seen.push("once");
      emitter.emit("event");
    });
    assert.equal(emitter.emit("event"), true);
    assert.deepEqual(seen, ["first", "once", "first", "late"]);
    assert.equal(emitter.listenerCount("event"), 3);
    assert.equal(emitter.emit("missing"), false);
  });
}

if (taskId === "typescript-url-router") {
  test("matches decoded paths with precedence, wildcards, and a query multimap", () => {
    expectDeclaration(/export\s+interface\s+Route\b/, "Route");
    expectDeclaration(/export\s+interface\s+RouteMatch\b/, "RouteMatch");
    const matched = implementation.matchRoute(
      [
        { name: "parameter", pattern: "/users/:id" },
        { name: "new-user", pattern: "/users/new" },
        { name: "files", pattern: "/files/*path" },
      ],
      "/users/new?tag=one&tag=two&space=a+b",
    );
    assert.equal(matched.name, "new-user");
    assert.deepEqual(matched.params, {});
    assert.deepEqual([...matched.query], [["tag", ["one", "two"]], ["space", ["a b"]]]);
    assert.deepEqual(
      implementation.matchRoute([{ name: "file", pattern: "/files/*path" }], "/files/a%20b/c"),
      { name: "file", params: { path: "a b/c" }, query: new Map() },
    );
    assert.equal(implementation.matchRoute([{ name: "x", pattern: "/x/:id" }], "/x/%E0%A4%A"), null);
    assert.throws(() => implementation.matchRoute([{ name: "bad", pattern: "/a/*x/b" }], "/a/b"), TypeError);
  });
}

if (taskId === "typescript-promise-pool") {
  test("preserves result order, bounds concurrency, and aborts peers on failure", async () => {
    expectDeclaration(/export\s+type\s+PoolWorker\s*</, "PoolWorker");
    expectDeclaration(/export\s+async\s+function\s+promisePool\s*</, "generic promisePool");
    let active = 0;
    let maximum = 0;
    const values = await implementation.promisePool([1, 2, 3, 4], async (value) => {
      active += 1;
      maximum = Math.max(maximum, active);
      await new Promise((resolve) => setTimeout(resolve, (5 - value) * 2));
      active -= 1;
      return value * 3;
    }, 2);
    assert.deepEqual(values, [3, 6, 9, 12]);
    assert.ok(maximum <= 2);

    const started = [];
    const aborted = [];
    const marker = new Error("worker failed");
    await assert.rejects(
      implementation.promisePool([0, 1, 2], async (value, index, signal) => {
        started.push(index);
        if (value === 1) throw marker;
        await new Promise((resolve) => signal.addEventListener("abort", () => {
          aborted.push(index);
          resolve();
        }, { once: true }));
        return value;
      }, 2),
      (error) => error === marker,
    );
    assert.deepEqual(started, [0, 1]);
    assert.deepEqual(aborted, [0]);
    await assert.rejects(implementation.promisePool([1], async (value) => value, 0), RangeError);
  });
}

if (taskId === "typescript-lru-ttl") {
  test("uses the injected clock for expiry and promotes LRU reads", () => {
    expectDeclaration(/export\s+interface\s+LruTtlOptions\b/, "LruTtlOptions");
    expectDeclaration(/export\s+class\s+LruTtlCache\s*</, "generic LruTtlCache");
    let now = 100;
    const cache = new implementation.LruTtlCache({ capacity: 2, ttlMs: 10, now: () => now });
    cache.set("a", 1).set("b", 2);
    assert.equal(cache.get("a"), 1);
    cache.set("c", 3);
    assert.equal(cache.get("b"), undefined);
    assert.equal(cache.get("a"), 1);
    now = 105;
    cache.set("c", 3);
    now = 110;
    assert.equal(cache.has("a"), false);
    assert.equal(cache.size, 1);
    cache.set("c", 4);
    assert.equal(cache.get("c"), 4);
    assert.throws(() => new implementation.LruTtlCache({ capacity: 0, ttlMs: 1 }), RangeError);
  });
}
