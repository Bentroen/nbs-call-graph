"""Analyze Note Block Studio GML sources and write call-graph artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import networkx as nx

from gml_analyze import (
    Unit,
    analyze_file,
    collect_project_functions,
    discover_gml_files,
    unit_to_dict,
)


def build_graph(
    units: list[Unit],
    call_counts: Counter[tuple[str, str]],
) -> nx.DiGraph:
    graph = nx.DiGraph()

    # First definition wins for node metrics if a name appears more than once.
    for unit in units:
        if unit.name not in graph:
            graph.add_node(
                unit.name,
                kind=unit.kind,
                file=unit.file,
                line=unit.line,
                lines=unit.lines,
                code_lines=unit.code_lines,
            )

    for (caller, callee), weight in call_counts.items():
        if caller not in graph:
            graph.add_node(caller)
        if callee not in graph:
            graph.add_node(callee)
        graph.add_edge(caller, callee, weight=weight)

    return graph


def write_outputs(
    out_dir: Path,
    units: list[Unit],
    graph: nx.DiGraph,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    functions_path = out_dir / "functions.json"
    csv_path = out_dir / "functions.csv"
    edgelist_path = out_dir / "call_graph.edgelist"
    graph_json_path = out_dir / "call_graph.json"

    unit_dicts = [unit_to_dict(u) for u in units]
    functions_path.write_text(
        json.dumps(unit_dicts, indent=2) + "\n",
        encoding="utf-8",
    )

    fieldnames = ["name", "file", "line", "kind", "lines", "code_lines"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unit_dicts)

    nx.write_edgelist(graph, edgelist_path, data=["weight"])

    nodes = []
    for name, attrs in graph.nodes(data=True):
        nodes.append({"id": name, **attrs})
    edges = [
        {"source": u, "target": v, "weight": data.get("weight", 1)}
        for u, v, data in graph.edges(data=True)
    ]
    graph_json_path.write_text(
        json.dumps({"nodes": nodes, "edges": edges}, indent=2) + "\n",
        encoding="utf-8",
    )


def run(root: Path, out_dir: Path) -> None:
    files = discover_gml_files(root)
    project_functions = collect_project_functions(root, files)

    all_units: list[Unit] = []
    call_counts: Counter[tuple[str, str]] = Counter()

    for path in files:
        source = path.read_text(encoding="utf-8", errors="replace")
        units, calls = analyze_file(path, root, source, project_functions)
        all_units.extend(units)
        call_counts.update(calls)

    all_units.sort(key=lambda u: (u.file, u.line, u.name))
    graph = build_graph(all_units, call_counts)
    write_outputs(out_dir, all_units, graph)

    multi = Counter(u.file for u in all_units if u.kind == "function")
    multi_files = sorted(f for f, n in multi.items() if n > 1)
    print(f"Files: {len(files)}")
    print(f"Function definitions: {sum(1 for u in all_units if u.kind == 'function')}")
    print(f"Object event units: {sum(1 for u in all_units if u.kind == 'object_event')}")
    print(f"Call edges: {graph.number_of_edges()}")
    print(f"Multi-function script files: {len(multi_files)}")
    for f in multi_files:
        print(f"  {f} ({multi[f]} functions)")
    print(f"Wrote artifacts to {out_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("NoteBlockStudio"),
        help="Project root containing .gml sources",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output"),
        help="Directory for output artifacts",
    )
    args = parser.parse_args()
    run(args.root.resolve(), args.out.resolve())


if __name__ == "__main__":
    main()
