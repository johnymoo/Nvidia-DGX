export class TypedEventEmitter {
  private listeners = new Map();

  on(event: string, listener: (...args: unknown[]) => void) {
    const entries = this.listeners.get(event) ?? [];
    entries.push(listener);
    this.listeners.set(event, entries);
  }

  emit(event: string, ...args: unknown[]) {
    for (const listener of this.listeners.get(event) ?? []) {
      listener(...args);
    }
  }
}
