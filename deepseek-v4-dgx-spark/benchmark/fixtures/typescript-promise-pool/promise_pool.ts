export async function promisePool<T, R>(items: readonly T[], worker: (item: T) => Promise<R>, _limit: number): Promise<R[]> {
  return Promise.all(items.map((item) => worker(item)));
}
