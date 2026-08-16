import assert from "node:assert/strict";
import test from "node:test";

import { promisePool } from "../promise_pool.ts";

test("maps inputs to results", async () => {
  assert.deepEqual(await promisePool([1, 2, 3], async (value) => value * 2, 2), [2, 4, 6]);
});
