import assert from "node:assert/strict";
import test from "node:test";

import { mergeConfig } from "../config_merge.ts";

test("merges a nested configuration", () => {
  assert.deepEqual(
    mergeConfig({ server: { port: 8080 }, enabled: true }, { server: { host: "127.0.0.1" } }),
    { server: { port: 8080, host: "127.0.0.1" }, enabled: true },
  );
});
