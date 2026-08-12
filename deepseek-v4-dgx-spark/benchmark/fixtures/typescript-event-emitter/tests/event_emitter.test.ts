import assert from "node:assert/strict";
import test from "node:test";

import { TypedEventEmitter } from "../event_emitter.ts";

test("delivers an event to a registered listener", () => {
  const emitter = new TypedEventEmitter<{ message: [string] }>();
  const received: string[] = [];
  emitter.on("message", (message) => received.push(message));
  emitter.emit("message", "hello");
  assert.deepEqual(received, ["hello"]);
});
