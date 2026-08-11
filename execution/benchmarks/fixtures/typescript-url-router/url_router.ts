export function matchRoute(routes: Array<{ name: string; pattern: string }>, input: string) {
  const pathname = input.split("?")[0];
  for (const route of routes) {
    const names = route.pattern.split("/").filter(Boolean);
    const values = pathname.split("/").filter(Boolean);
    if (names.length !== values.length) {
      continue;
    }
    const params: Record<string, string> = {};
    let matched = true;
    for (let index = 0; index < names.length; index += 1) {
      if (names[index].startsWith(":")) {
        params[names[index].slice(1)] = values[index];
      } else if (names[index] !== values[index]) {
        matched = false;
      }
    }
    if (matched) {
      return { name: route.name, params, query: new Map() };
    }
  }
  return null;
}
