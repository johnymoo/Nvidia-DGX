"""Stable topological ordering with useful dependency diagnostics."""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping
from typing import TypeVar


T = TypeVar("T", bound=Hashable)


class MissingDependencyError(KeyError):
    def __init__(self, node: T, dependency: T):
        self.node = node
        self.dependency = dependency
        super().__init__(f"{node!r} depends on missing node {dependency!r}")


class DependencyCycleError(ValueError):
    def __init__(self, cycle: tuple[T, ...]):
        self.cycle = cycle
        super().__init__("dependency cycle: " + " -> ".join(map(str, cycle)))


def stable_toposort(graph: Mapping[T, Iterable[T]]) -> list[T]:
    """Return dependencies before dependents, preserving mapping and edge order."""
    dependencies = {node: tuple(values) for node, values in graph.items()}
    for node, values in dependencies.items():
        for dependency in values:
            if dependency not in dependencies:
                raise MissingDependencyError(node, dependency)

    state: dict[T, int] = {}
    path: list[T] = []
    path_index: dict[T, int] = {}
    ordered: list[T] = []

    def visit(node: T) -> None:
        current_state = state.get(node, 0)
        if current_state == 2:
            return
        if current_state == 1:
            start = path_index[node]
            raise DependencyCycleError(tuple(path[start:] + [node]))

        state[node] = 1
        path_index[node] = len(path)
        path.append(node)
        for dependency in dependencies[node]:
            visit(dependency)
        path.pop()
        path_index.pop(node, None)
        state[node] = 2
        ordered.append(node)

    for node in dependencies:
        visit(node)
    return ordered
