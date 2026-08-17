import assert from "node:assert/strict";
import test from "node:test";

import { matchRoute } from "../url_router.ts";

test("matches a named parameter", () => {
  assert.deepEqual(
    matchRoute([{ name: "user", pattern: "/users/:id" }], "/users/42"),
    { name: "user", params: { id: "42" }, query: new Map() },
  );
});
