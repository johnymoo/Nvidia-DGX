export type EventMap = { [event: string]: readonly unknown[] };
export type Listener<Arguments extends readonly unknown[]> = (...args: Arguments) => void;

type Entry = {
  listener: (...args: unknown[]) => void;
  once: boolean;
};

export class TypedEventEmitter<Events extends { [K in keyof Events]: readonly unknown[] }> {
  private listeners: Map<keyof Events, Entry[]> = new Map();

  on<Key extends keyof Events>(event: Key, listener: Listener<Events[Key]>): () => void {
    const entry: Entry = { listener: listener as (...args: unknown[]) => void, once: false };
    this.add(event, entry);
    return () => this.removeEntry(event, entry);
  }

  once<Key extends keyof Events>(event: Key, listener: Listener<Events[Key]>): () => void {
    const entry: Entry = { listener: listener as (...args: unknown[]) => void, once: true };
    this.add(event, entry);
    return () => this.removeEntry(event, entry);
  }

  off<Key extends keyof Events>(event: Key, listener: Listener<Events[Key]>): boolean {
    const entries = this.listeners.get(event);
    if (!entries) {
      return false;
    }
    for (let index = entries.length - 1; index >= 0; index -= 1) {
      if (entries[index].listener === listener) {
        entries.splice(index, 1);
        if (entries.length === 0) {
          this.listeners.delete(event);
        }
        return true;
      }
    }
    return false;
  }

  emit<Key extends keyof Events>(event: Key, ...args: Events[Key]): boolean {
    const snapshot = [...(this.listeners.get(event) ?? [])];
    for (const entry of snapshot) {
      const current = this.listeners.get(event);
      if (!current || !current.includes(entry)) {
        continue;
      }
      if (entry.once) {
        this.removeEntry(event, entry);
      }
      entry.listener(...args);
    }
    return snapshot.length > 0;
  }

  listenerCount<Key extends keyof Events>(event: Key): number {
    return this.listeners.get(event)?.length ?? 0;
  }

  private add<Key extends keyof Events>(event: Key, entry: Entry): void {
    const entries = this.listeners.get(event) ?? [];
    entries.push(entry);
    this.listeners.set(event, entries);
  }

  private removeEntry<Key extends keyof Events>(event: Key, entry: Entry): boolean {
    const entries = this.listeners.get(event);
    if (!entries) {
      return false;
    }
    const index = entries.indexOf(entry);
    if (index < 0) {
      return false;
    }
    entries.splice(index, 1);
    if (entries.length === 0) {
      this.listeners.delete(event);
    }
    return true;
  }
}
