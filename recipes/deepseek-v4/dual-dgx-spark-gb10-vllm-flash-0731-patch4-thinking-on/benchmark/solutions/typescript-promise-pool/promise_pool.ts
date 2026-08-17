export type PoolWorker<T, R> = (item: T, index: number, signal: AbortSignal) => Promise<R> | R;

export async function promisePool<T, R>(
  items: readonly T[],
  worker: PoolWorker<T, R>,
  limit: number,
): Promise<R[]> {
  if (!Number.isSafeInteger(limit) || limit <= 0) {
    throw new RangeError("limit must be a positive safe integer");
  }
  if (typeof worker !== "function") {
    throw new TypeError("worker must be a function");
  }

  const controller = new AbortController();
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  let firstFailure: unknown = undefined;

  const runWorker = async (): Promise<void> => {
    while (!controller.signal.aborted) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= items.length) return;
      try {
        results[index] = await worker(items[index], index, controller.signal);
      } catch (error) {
        if (!controller.signal.aborted) {
          firstFailure = error;
          controller.abort(error);
        }
        return;
      }
    }
  };

  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, runWorker));
  if (controller.signal.aborted) {
    throw firstFailure;
  }
  return results;
}
