"""Return a dependency ordering."""


def stable_toposort(graph):
    remaining = {node: set(dependencies) for node, dependencies in graph.items()}
    result = []
    while remaining:
        ready = [node for node, dependencies in remaining.items() if not dependencies]
        if not ready:
            raise ValueError("cycle")
        for node in ready:
            result.append(node)
            remaining.pop(node)
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    return result
