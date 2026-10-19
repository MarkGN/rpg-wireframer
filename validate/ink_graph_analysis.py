from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Any

from validate.ink_compiler import find_ink_path, ink_json_path
from validate.ink_graph import _build_graph_from_story, _collect_scenario_graph_edges


def _reachability_aliases(name: str, graph: dict[str, set[str]]) -> set[str]:
    aliases = {name}
    if "." not in name:
        return aliases
    flat_name = name.replace(".", "")
    if flat_name not in graph:
        aliases.add(flat_name)
    return aliases


def _collect_reachable_knots(graph: dict[str, set[str]]) -> set[str]:
    visited: set[str] = set()
    stack = ["__root__"]
    while stack:
        current = stack.pop()
        current_aliases = _reachability_aliases(current, graph)
        if current_aliases & visited:
            continue
        visited.update(current_aliases)
        for successor in graph.get(current, []):
            successor_aliases = _reachability_aliases(successor, graph)
            if not (successor_aliases & visited):
                stack.append(successor)
    return visited


def analyze_ink_file(
    ink_filename: str,
    dialogue_dir: Path,
    game_path: Path | None = None,
    external_argument_resolver: Callable[[str, list[Any], str], Any] | None = None,
    phase_timings: dict[str, float] | None = None,
) -> tuple[
    dict[str, set[str]],
    list[tuple[str, str]],
    dict[str, list[tuple[str, str, bool]]],
    dict[str, list[tuple[str, Any]]],
    dict[str, list[tuple[str, str, str, bool]]],
    dict[str, list[tuple[str, str, bool]]],
    dict[str, list[tuple[str, str, str]]],
    dict[str, list[tuple[str, Any]]],
]:
    compile_started = monotonic()
    try:
        json_path = ink_json_path(ink_filename, dialogue_dir)
    finally:
        if phase_timings is not None:
            phase_timings["Ink compilation"] = (
                phase_timings.get("Ink compilation", 0.0)
                + monotonic()
                - compile_started
            )

    analysis_started = monotonic()
    try:
        with open(json_path, encoding="utf-8") as f:
            story_data = json.load(f)

        (
            graph,
            scenario_calls,
            get_conditions,
            set_mutations,
            has_conditions,
            list_mutations,
            move_mutations,
            guard_expressions,
        ) = _build_graph_from_story(story_data, external_argument_resolver)
        if game_path is not None:
            ink_path = find_ink_path(ink_filename, dialogue_dir) or (
                dialogue_dir / ink_filename
            )
            _collect_scenario_graph_edges(graph, scenario_calls, game_path, ink_path)
    finally:
        if phase_timings is not None:
            phase_timings["Dialogue analysis"] = (
                phase_timings.get("Dialogue analysis", 0.0)
                + monotonic()
                - analysis_started
            )

    return (
        graph,
        scenario_calls,
        get_conditions,
        set_mutations,
        has_conditions,
        list_mutations,
        move_mutations,
        guard_expressions,
    )
