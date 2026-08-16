export class LruTtlCache<K, V> {
  private entries = new Map<K, V>();

  constructor(_options: { capacity: number; ttlMs: number; now?: () => number }) {}

  get(key: K): V | undefined {
    return this.entries.get(key);
  }

  set(key: K, value: V): this {
    this.entries.set(key, value);
    return this;
  }

  get size(): number {
    return this.entries.size;
  }
}
