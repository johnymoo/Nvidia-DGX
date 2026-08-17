export interface LruTtlOptions {
  capacity: number;
  ttlMs: number;
  now?: () => number;
}

type Entry<V> = { value: V; expiresAt: number };

export class LruTtlCache<K, V> {
  private readonly capacity: number;
  private readonly ttlMs: number;
  private readonly now: () => number;
  private entries: Map<K, Entry<V>> = new Map();

  constructor(options: LruTtlOptions) {
    if (!options || !Number.isSafeInteger(options.capacity) || options.capacity <= 0) {
      throw new RangeError("capacity must be a positive safe integer");
    }
    if (!Number.isFinite(options.ttlMs) || options.ttlMs < 0) {
      throw new RangeError("ttlMs must be a finite non-negative number");
    }
    if (options.now !== undefined && typeof options.now !== "function") {
      throw new TypeError("now must be a function");
    }
    this.capacity = options.capacity;
    this.ttlMs = options.ttlMs;
    this.now = options.now ?? Date.now;
  }

  get(key: K): V | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    if (this.isExpired(entry)) {
      this.entries.delete(key);
      return undefined;
    }
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.value;
  }

  has(key: K): boolean {
    const entry = this.entries.get(key);
    if (!entry) return false;
    if (this.isExpired(entry)) {
      this.entries.delete(key);
      return false;
    }
    return true;
  }

  set(key: K, value: V): this {
    this.removeExpired();
    this.entries.delete(key);
    this.entries.set(key, { value, expiresAt: this.now() + this.ttlMs });
    while (this.entries.size > this.capacity) {
      const oldest = this.entries.keys().next().value as K | undefined;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
    return this;
  }

  delete(key: K): boolean {
    return this.entries.delete(key);
  }

  clear(): void {
    this.entries.clear();
  }

  get size(): number {
    this.removeExpired();
    return this.entries.size;
  }

  private isExpired(entry: Entry<V>): boolean {
    return this.now() >= entry.expiresAt;
  }

  private removeExpired(): void {
    for (const [key, entry] of this.entries) {
      if (this.isExpired(entry)) this.entries.delete(key);
    }
  }
}
