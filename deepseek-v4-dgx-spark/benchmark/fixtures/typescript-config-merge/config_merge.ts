export function mergeConfig(base: Record<string, unknown>, override: Record<string, unknown>) {
  return { ...base, ...override };
}
