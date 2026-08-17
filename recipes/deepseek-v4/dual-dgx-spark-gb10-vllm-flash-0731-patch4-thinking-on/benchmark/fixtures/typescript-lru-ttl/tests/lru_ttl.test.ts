import assert from "node:assert/strict";
import test from "node:test";

import { LruTtlCache } from "../lru_ttl.ts";

test("stores and retrieves a value", () => {
  const cache = new LruTtlCache<string, number>({ capacity: 2, ttlMs: 10 });
  cache.set("one", 1);
  assert.equal(cache.get("one"), 1);
  assert.equal(cache.size, 1);
});
