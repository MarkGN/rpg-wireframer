from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from validate.ink_analyser_constants import (
    INTERNAL_TARGETS,
)
from validate.ink_bytecode import (
    _choice_sources,
    _collect_choice_bodies,
    _find_dialogue_conditions,
    _find_divert_targets,
    _find_list_mutations,
    _find_move_mutations,
    _find_set_mutations,
    _parse_scenario_outcomes,
)
from validate.ink_compiler import load_yaml


def _build_graph_from_story(
    story_data: dict[str, Any],
    external_argument_resolver: Callable[[str, list[Any], str], Any] | None = None,
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
    if "root" not in story_data or not isinstance(story_data["root"], list):
        raise ValueError("Compiled Ink JSON did not contain a valid root element")

    root = story_data["root"]
    if len(root) < 3 or not isinstance(root[0], list):
        raise ValueError(
            f"Compiled Ink JSON root structure is malformed: full data {story_data}"
        )

    knots_container = root[2] if isinstance(root[2], dict) else {}
    knots = set(knots_container.keys())
    graph: dict[str, set[str]] = {"__root__": set()}
    get_conditions: dict[str, list[tuple[str, str, bool]]] = {"__root__": []}
    has_conditions: dict[str, list[tuple[str, str, str, bool]]] = {"__root__": []}
    set_mutations: dict[str, list[tuple[str, Any]]] = {"__root__": []}
    list_mutations: dict[str, list[tuple[str, str, bool]]] = {"__root__": []}
    move_mutations: dict[str, list[tuple[str, str, str]]] = {"__root__": []}
    guard_expressions: dict[str, list[tuple[str, Any]]] = {"__root__": []}
    stitch_names_by_knot: dict[str, list[str]] = {}
    for knot in knots:
        graph[knot] = set()
        get_conditions[knot] = []
        has_conditions[knot] = []
        set_mutations[knot] = []
        list_mutations[knot] = []
        move_mutations[knot] = []
        guard_expressions[knot] = []
        stitches = _collect_stitch_names(knots_container[knot], prefix=knot)
        stitch_names_by_knot[knot] = sorted(stitches)
        for stitch_name in stitch_names_by_knot[knot]:
            if stitch_name in graph:
                continue
            graph[stitch_name] = set()
            get_conditions[stitch_name] = []
            has_conditions[stitch_name] = []
            set_mutations[stitch_name] = []
            list_mutations[stitch_name] = []
            move_mutations[stitch_name] = []
            guard_expressions[stitch_name] = []

    root_targets, root_scenarios = _find_divert_targets(root[0], "__root__")
    graph["__root__"].update(
        t for t in root_targets if t in graph or t in INTERNAL_TARGETS
    )
    for _, script in root_scenarios:
        target = f"__scenario__{script}"
        graph["__root__"].add(target)
        graph.setdefault(target, set())
        get_conditions.setdefault(target, [])
        has_conditions.setdefault(target, [])
        set_mutations.setdefault(target, [])
        list_mutations.setdefault(target, [])
        move_mutations.setdefault(target, [])
        guard_expressions.setdefault(target, [])
    root_gets, root_hass, root_expressions = _find_dialogue_conditions(
        root[0], "__root__"
    )
    get_conditions["__root__"].extend(root_gets)
    has_conditions["__root__"].extend(root_hass)
    guard_expressions["__root__"].extend(root_expressions)
    for target, _, _ in root_gets:
        if target.startswith("__content__"):
            graph["__root__"].add(target)
            graph[target] = set()
            get_conditions[target] = []
            has_conditions[target] = []
            set_mutations[target] = []
            list_mutations[target] = []
            guard_expressions[target] = []
        elif target.startswith("__scenario__"):
            graph["__root__"].add(target)
            graph.setdefault(target, set())
            get_conditions.setdefault(target, [])
            has_conditions.setdefault(target, [])
            set_mutations.setdefault(target, [])
            list_mutations.setdefault(target, [])
            move_mutations.setdefault(target, [])
            guard_expressions.setdefault(target, [])
    for target, _, _, _ in root_hass:
        if target.startswith("__content__"):
            graph["__root__"].add(target)
            graph[target] = set()
            get_conditions[target] = []
            has_conditions[target] = []
            set_mutations[target] = []
            list_mutations[target] = []
            guard_expressions[target] = []
        elif target.startswith("__scenario__"):
            graph["__root__"].add(target)
            graph.setdefault(target, set())
            get_conditions.setdefault(target, [])
            has_conditions.setdefault(target, [])
            set_mutations.setdefault(target, [])
            list_mutations.setdefault(target, [])
            move_mutations.setdefault(target, [])
            guard_expressions.setdefault(target, [])
    root_choice_bodies = _collect_choice_bodies(root[0])
    root_choice_keys = set(root_choice_bodies)
    choice_sources = {
        target for target, _, _ in root_gets if target.startswith("__content__")
    } | {target for target, _, _, _ in root_hass if target.startswith("__content__")}
    choice_sources = _choice_sources(
        "__root__",
        graph,
        get_conditions,
        has_conditions,
        guard_expressions,
        root_gets,
        root_hass,
        root_expressions,
        choice_sources,
    )
    for choice_key, choice_body in root_choice_bodies.items():
        choice_target = f"__choice____root____{choice_key}"
        for source in choice_sources:
            graph.setdefault(source, set()).add(choice_target)
        graph.setdefault(choice_target, set())
        get_conditions.setdefault(choice_target, [])
        has_conditions.setdefault(choice_target, [])
        set_mutations[choice_target] = _find_set_mutations(choice_body, choice_target)
        list_mutations[choice_target] = _find_list_mutations(
            choice_body,
            choice_target,
            external_argument_resolver,
        )
        move_mutations[choice_target] = _find_move_mutations(choice_body, choice_target)
        guard_expressions.setdefault(choice_target, [])
    raw_root_sets = _find_set_mutations(root[0], "__root__", root_choice_keys)
    temp_var_mutations = {
        key for key, val in raw_root_sets if isinstance(val, dict) and "VAR?" in val
    }
    if temp_var_mutations:
        for target, expr in root_expressions:
            if (
                isinstance(expr, tuple)
                and expr[0] == "=="
                and isinstance(expr[1], tuple)
                and expr[1][0] == "get"
                and isinstance(expr[2], int)
            ):
                var_name = expr[1][1]
                if var_name in temp_var_mutations and (
                    var_name,
                    expr[2] + 1,
                ) not in set_mutations.get(target, []):
                    set_mutations.setdefault(target, []).append((var_name, expr[2] + 1))
        fallthrough_targets = [
            t
            for t in graph["__root__"]
            if t not in {target for target, _ in root_expressions}
            and t in knots_container
        ]
        for ft in fallthrough_targets:
            for key, val in raw_root_sets:
                if (
                    isinstance(val, (int, str, bool))
                    and key in temp_var_mutations
                    and (key, val) not in set_mutations.get(ft, [])
                ):
                    set_mutations.setdefault(ft, []).append((key, val))
        set_mutations["__root__"] = [
            (k, v) for k, v in raw_root_sets if k not in temp_var_mutations
        ]
    else:
        set_mutations["__root__"].extend(raw_root_sets)
    list_mutations["__root__"].extend(
        _find_list_mutations(
            root[0],
            "__root__",
            external_argument_resolver,
            root_choice_keys,
        )
    )
    move_mutations["__root__"].extend(
        _find_move_mutations(root[0], "__root__", root_choice_keys)
    )

    for knot_name, knot_body in knots_container.items():
        targets, scenario_calls = _find_divert_targets(knot_body, knot_name)
        graph[knot_name].update(
            t for t in targets if t in graph or t in INTERNAL_TARGETS
        )
        for _, script in scenario_calls:
            target = f"__scenario__{script}"
            graph[knot_name].add(target)
            graph.setdefault(target, set())
            get_conditions.setdefault(target, [])
            has_conditions.setdefault(target, [])
            set_mutations.setdefault(target, [])
            list_mutations.setdefault(target, [])
            move_mutations.setdefault(target, [])
            guard_expressions.setdefault(target, [])
        root_scenarios.extend(scenario_calls)
        knot_gets, knot_hass, knot_expressions = _find_dialogue_conditions(
            knot_body, knot_name
        )
        get_conditions[knot_name].extend(knot_gets)
        has_conditions[knot_name].extend(knot_hass)
        guard_expressions[knot_name].extend(knot_expressions)
        for target, _, _ in knot_gets:
            if target.startswith("__content__"):
                graph[knot_name].add(target)
                graph[target] = set()
                get_conditions[target] = []
                has_conditions[target] = []
                set_mutations[target] = []
                list_mutations[target] = []
                move_mutations[target] = []
                guard_expressions[target] = []
            elif target.startswith("__scenario__"):
                graph[knot_name].add(target)
                graph.setdefault(target, set())
                get_conditions.setdefault(target, [])
                has_conditions.setdefault(target, [])
                set_mutations.setdefault(target, [])
                list_mutations.setdefault(target, [])
                move_mutations.setdefault(target, [])
                guard_expressions.setdefault(target, [])
        for target, _, _, _ in knot_hass:
            if target.startswith("__content__"):
                graph[knot_name].add(target)
                graph[target] = set()
                get_conditions[target] = []
                has_conditions[target] = []
                set_mutations[target] = []
                list_mutations[target] = []
                move_mutations[target] = []
                guard_expressions[target] = []
            elif target.startswith("__scenario__"):
                graph[knot_name].add(target)
                graph.setdefault(target, set())
                get_conditions.setdefault(target, [])
                has_conditions.setdefault(target, [])
                set_mutations.setdefault(target, [])
                list_mutations.setdefault(target, [])
                move_mutations.setdefault(target, [])
                guard_expressions.setdefault(target, [])
        knot_choice_bodies = _collect_choice_bodies(knot_body)
        knot_choice_keys = set(knot_choice_bodies)
        choice_sources = {
            target for target, _, _ in knot_gets if target.startswith("__content__")
        } | {
            target for target, _, _, _ in knot_hass if target.startswith("__content__")
        }
        choice_sources = _choice_sources(
            knot_name,
            graph,
            get_conditions,
            has_conditions,
            guard_expressions,
            knot_gets,
            knot_hass,
            knot_expressions,
            choice_sources,
        )
        for choice_key, choice_body in knot_choice_bodies.items():
            choice_target = f"__choice__{knot_name}__{choice_key}"
            for source in choice_sources:
                graph.setdefault(source, set()).add(choice_target)
            graph.setdefault(choice_target, set())
            get_conditions.setdefault(choice_target, [])
            has_conditions.setdefault(choice_target, [])
            set_mutations[choice_target] = _find_set_mutations(
                choice_body, choice_target
            )
            list_mutations[choice_target] = _find_list_mutations(
                choice_body,
                choice_target,
                external_argument_resolver,
            )
            move_mutations[choice_target] = _find_move_mutations(
                choice_body, choice_target
            )
            guard_expressions.setdefault(choice_target, [])
        set_mutations[knot_name].extend(
            _find_set_mutations(knot_body, knot_name, knot_choice_keys)
        )
        list_mutations[knot_name].extend(
            _find_list_mutations(
                knot_body,
                knot_name,
                external_argument_resolver,
                knot_choice_keys,
            )
        )
        move_mutations[knot_name].extend(
            _find_move_mutations(knot_body, knot_name, knot_choice_keys)
        )

    for knot_name, stitch_names in stitch_names_by_knot.items():
        for stitch_name in stitch_names:
            if stitch_name not in graph:
                continue
            graph[stitch_name].update(graph.get(knot_name, set()))
            get_conditions[stitch_name].extend(get_conditions.get(knot_name, []))
            has_conditions[stitch_name].extend(has_conditions.get(knot_name, []))
            set_mutations[stitch_name].extend(set_mutations.get(knot_name, []))
            list_mutations[stitch_name].extend(list_mutations.get(knot_name, []))
            move_mutations[stitch_name].extend(move_mutations.get(knot_name, []))
            guard_expressions[stitch_name].extend(guard_expressions.get(knot_name, []))

    # Tunnel calls transfer control to another flow and tunnel returns resume
    # the caller. Add the call and return edges to the same graph used by
    # dialogue reachability and quest planning.
    tunnel_calls: list[tuple[str, str]] = []
    tunnel_return_nodes: dict[str, set[str]] = {}
    for flow_name, body in {"__root__": root[0], **knots_container}.items():
        choice_bodies = _collect_choice_bodies(body)
        choice_keys = set(choice_bodies)
        tunnel_calls.extend(
            (flow_name, target)
            for target in _collect_tunnel_calls(body, choice_keys)
        )

        for choice_key, choice_body in choice_bodies.items():
            choice_target = f"__choice__{flow_name}__{choice_key}"
            if choice_target not in graph:
                continue
            tunnel_calls.extend(
                (choice_target, target)
                for target in _collect_tunnel_calls(choice_body, set())
            )
            if _count_tunnel_returns(choice_body):
                tunnel_return_nodes.setdefault(flow_name, set()).add(choice_target)

        if _count_tunnel_returns(body, choice_keys):
            tunnel_return_nodes.setdefault(flow_name, set()).add(flow_name)

    for caller, tunnel in tunnel_calls:
        for return_node in tunnel_return_nodes.get(tunnel, set()):
            graph.setdefault(return_node, set()).add(caller)

    return (
        graph,
        root_scenarios,
        get_conditions,
        set_mutations,
        has_conditions,
        list_mutations,
        move_mutations,
        guard_expressions,
    )


def _collect_scenario_graph_edges(
    graph: dict[str, set[str]],
    scenario_calls: list[tuple[str, str]],
    game_path: Path,
    dialogue_file: Path,
) -> None:
    scenario_dir = game_path / "world" / "scenarios"
    for origin, script in scenario_calls:
        scenario_path = scenario_dir / f"{script}.yaml"
        if not scenario_path.exists():
            raise ValueError(
                f"{dialogue_file}: scenario file '{scenario_path.relative_to(game_path)}' not found"
            )
        raw = load_yaml(scenario_path)
        if not isinstance(raw, dict):
            raise TypeError(
                f"{dialogue_file}: scenario file '{scenario_path.relative_to(game_path)}' must contain a mapping"
            )
        context = raw.get("context")
        if not isinstance(context, str):
            raise TypeError(
                f"{dialogue_file}: scenario file '{scenario_path.relative_to(game_path)}' missing or invalid 'context'"
            )
        if context == "encounter":
            outcomes_raw = raw.get("outcomes")
            if outcomes_raw is None:
                raise ValueError(
                    f"{dialogue_file}: scenario file '{scenario_path.relative_to(game_path)}' must define 'outcomes' for encounter context"
                )
            outcomes = _parse_scenario_outcomes(outcomes_raw, scenario_path)
            for target in outcomes.values():
                graph[origin].add(target)
        elif context == "shop" or context == "craft":
            pass
        else:
            raise ValueError(
                f"{dialogue_file}: unsupported scenario context '{context}' in '{scenario_path.relative_to(game_path)}'"
            )


def _collect_stitch_names(node: Any, prefix: str = "") -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"#n", "#f", "#a", "#b", "#c"}:
                continue
            if isinstance(value, (dict, list)):
                full = f"{prefix}.{key}" if prefix else key
                names.add(full)
                names.update(_collect_stitch_names(value, full))
    elif isinstance(node, list):
        for item in node:
            names.update(_collect_stitch_names(item, prefix))
    return names


def _count_tunnel_returns(node: Any, excluded_keys: set[str] | None = None) -> int:
    if excluded_keys is None:
        excluded_keys = set()
    if node == "->->":
        return 1
    if isinstance(node, dict):
        return sum(
            _count_tunnel_returns(value, excluded_keys)
            for key, value in node.items()
            if key not in excluded_keys
        )
    if isinstance(node, list):
        return sum(_count_tunnel_returns(value, excluded_keys) for value in node)
    return 0


def _collect_tunnel_calls(node: Any, excluded_keys: set[str]) -> set[str]:
    calls: set[str] = set()
    if isinstance(node, dict):
        target = node.get("->t->")
        if isinstance(target, str) and not target.startswith("."):
            calls.add(target)
        for key, value in node.items():
            if key not in excluded_keys:
                calls.update(_collect_tunnel_calls(value, excluded_keys))
    elif isinstance(node, list):
        for value in node:
            calls.update(_collect_tunnel_calls(value, excluded_keys))
    return calls
