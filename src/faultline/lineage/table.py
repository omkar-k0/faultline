"""Table-level lineage: a directed graph of dbt nodes, upstream to downstream."""

from __future__ import annotations

from typing import Any

import networkx as nx

from faultline.collectors.dbt_artifacts import Project


def build_table_graph(project: Project) -> Any:
    """Return a `networkx.DiGraph` with an edge parent -> child for every dependency.

    Node attributes: `resource_type`, `name`. Dependencies on nodes outside the
    manifest (disabled models, other projects) are kept as nodes with
    `resource_type="external"` so no edge is silently dropped.
    """
    graph = nx.DiGraph()
    for node in project.nodes.values():
        graph.add_node(node.unique_id, resource_type=node.resource_type, name=node.name)
    for node in project.nodes.values():
        for parent in node.depends_on:
            if parent not in graph:
                graph.add_node(parent, resource_type="external", name=parent.rsplit(".", 1)[-1])
            graph.add_edge(parent, node.unique_id)
    return graph
