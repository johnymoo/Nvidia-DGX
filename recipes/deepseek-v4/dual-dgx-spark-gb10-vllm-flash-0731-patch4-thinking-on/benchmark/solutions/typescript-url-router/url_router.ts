export interface Route {
  name: string;
  pattern: string;
}

export interface RouteMatch {
  name: string;
  params: Record<string, string>;
  query: Map<string, string[]>;
}

type Segment =
  | { kind: "static"; value: string }
  | { kind: "parameter"; name: string }
  | { kind: "wildcard"; name: string };

type CompiledRoute = { route: Route; segments: Segment[]; order: number };

function pathSegments(path: string): string[] {
  if (!path.startsWith("/")) {
    throw new TypeError("paths must start with a slash");
  }
  const raw = path.split("/").slice(1);
  if (raw.length > 0 && raw[raw.length - 1] === "") {
    raw.pop();
  }
  try {
    return raw.map((segment) => decodeURIComponent(segment));
  } catch {
    throw new TypeError("path contains invalid percent encoding");
  }
}

function compile(route: Route, order: number): CompiledRoute {
  if (!route || typeof route.name !== "string" || typeof route.pattern !== "string") {
    throw new TypeError("routes must have string names and patterns");
  }
  if (route.pattern.includes("?") || route.pattern.includes("#")) {
    throw new TypeError("route patterns cannot contain query or fragment text");
  }
  const names = new Set<string>();
  const segments = pathSegments(route.pattern).map((value, index, values): Segment => {
    if (value.startsWith(":")) {
      const name = value.slice(1);
      if (!name || names.has(name)) {
        throw new TypeError("parameter names must be unique and non-empty");
      }
      names.add(name);
      return { kind: "parameter", name };
    }
    if (value.startsWith("*")) {
      const name = value.slice(1);
      if (!name || index !== values.length - 1 || names.has(name)) {
        throw new TypeError("wildcards must be final and uniquely named");
      }
      names.add(name);
      return { kind: "wildcard", name };
    }
    return { kind: "static", value };
  });
  return { route, segments, order };
}

function comparePrecedence(left: CompiledRoute, right: CompiledRoute): number {
  const weight = (segment: Segment | undefined): number => {
    if (!segment) return 0;
    if (segment.kind === "static") return 3;
    if (segment.kind === "parameter") return 2;
    return 1;
  };
  const length = Math.max(left.segments.length, right.segments.length);
  for (let index = 0; index < length; index += 1) {
    const difference = weight(right.segments[index]) - weight(left.segments[index]);
    if (difference !== 0) return difference;
  }
  return left.order - right.order;
}

function matches(route: CompiledRoute, values: string[]): Record<string, string> | null {
  const params: Record<string, string> = {};
  let valueIndex = 0;
  for (let index = 0; index < route.segments.length; index += 1) {
    const segment = route.segments[index];
    if (segment.kind === "wildcard") {
      params[segment.name] = values.slice(valueIndex).join("/");
      return params;
    }
    const value = values[valueIndex];
    if (value === undefined) return null;
    if (segment.kind === "static" && segment.value !== value) return null;
    if (segment.kind === "parameter") params[segment.name] = value;
    valueIndex += 1;
  }
  return valueIndex === values.length ? params : null;
}

export function matchRoute(routes: readonly Route[], input: string): RouteMatch | null {
  if (typeof input !== "string") {
    throw new TypeError("input must be a string");
  }
  let url: URL;
  try {
    url = new URL(input, "http://router.invalid");
  } catch {
    return null;
  }
  let values: string[];
  try {
    values = pathSegments(url.pathname);
  } catch {
    return null;
  }
  const candidates = routes.map(compile).sort(comparePrecedence);
  for (const route of candidates) {
    const params = matches(route, values);
    if (params === null) continue;
    const query = new Map<string, string[]>();
    for (const [key, value] of url.searchParams) {
      const entries = query.get(key) ?? [];
      entries.push(value);
      query.set(key, entries);
    }
    return { name: route.route.name, params, query };
  }
  return null;
}
