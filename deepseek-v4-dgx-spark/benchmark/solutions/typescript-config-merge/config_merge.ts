export interface MergeOptions {
  array: "replace" | "concat";
  undefined: "ignore" | "overwrite";
}

type PlainObject = Record<string, unknown>;

const defaults: MergeOptions = { array: "replace", undefined: "ignore" };

function isPlainObject(value: unknown): value is PlainObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function copy(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(copy);
  }
  if (isPlainObject(value)) {
    const result: PlainObject = {};
    for (const key of Object.keys(value)) {
      result[key] = copy(value[key]);
    }
    return result;
  }
  return value;
}

function mergeValue(base: unknown, override: unknown, options: MergeOptions): unknown {
  if (override === undefined) {
    return options.undefined === "overwrite" ? undefined : copy(base);
  }
  if (Array.isArray(base) && Array.isArray(override)) {
    return options.array === "concat" ? [...base.map(copy), ...override.map(copy)] : override.map(copy);
  }
  if (isPlainObject(base) && isPlainObject(override)) {
    const result: PlainObject = {};
    for (const key of Object.keys(base)) {
      result[key] = copy(base[key]);
    }
    for (const key of Object.keys(override)) {
      if (override[key] === undefined && options.undefined === "ignore") {
        continue;
      }
      result[key] = mergeValue(base[key], override[key], options);
    }
    return result;
  }
  return copy(override);
}

export function mergeConfig<T extends PlainObject, U extends PlainObject>(
  base: T,
  override: U,
  options: Partial<MergeOptions> = {},
): T & U {
  const resolved: MergeOptions = { ...defaults, ...options };
  if (resolved.array !== "replace" && resolved.array !== "concat") {
    throw new TypeError("array must be replace or concat");
  }
  if (resolved.undefined !== "ignore" && resolved.undefined !== "overwrite") {
    throw new TypeError("undefined must be ignore or overwrite");
  }
  if (!isPlainObject(base) || !isPlainObject(override)) {
    throw new TypeError("base and override must be plain objects");
  }
  return mergeValue(base, override, resolved) as T & U;
}
