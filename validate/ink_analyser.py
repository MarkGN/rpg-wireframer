from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

SCENARIO_FUNCTION = "scenario"
INTERNAL_DIVERT_PREFIX = "."
INTERNAL_TARGETS = {"done"}


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return raw or {}


def find_ink_path(ink_filename: str, dialogue_dir: Path) -> Path | None:
    candidate = dialogue_dir / ink_filename
    if candidate.exists():
        return candidate

    target_name = Path(ink_filename).name
    for path in sorted(dialogue_dir.rglob("*.ink")):
        if path.name == target_name:
            return path

    return None


def load_custom_externals_definitions(dialogue_dir: Path) -> dict[str, int]:
    custom_path = dialogue_dir / "custom_externals.yaml"
    if not custom_path.exists():
        return {}

    with open(custom_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise TypeError(f"Expected mapping in {custom_path}, got {type(raw).__name__}")

    custom_externals: dict[str, int] = {}
    for name, spec in raw.items():
        if not isinstance(name, str):
            raise TypeError(f"Invalid custom external name {name!r} in {custom_path}")
        if isinstance(spec, dict) and "args" in spec:
            arg_count = spec["args"]
        elif isinstance(spec, int):
            arg_count = spec
        else:
            raise ValueError(
                f"Invalid custom external spec for {name!r} in {custom_path}: {spec!r}"
            )
        if not isinstance(arg_count, int) or arg_count < 0:
            raise ValueError(
                f"Invalid arg count for {name!r} in {custom_path}: {arg_count!r}"
            )
        custom_externals[name] = arg_count
    return custom_externals


def ink_json_path(ink_filename: str, dialogue_dir: Path) -> Path:
    ink_path = find_ink_path(ink_filename, dialogue_dir)
    if ink_path is None:
        raise ValueError(f"Dialogue file not found: {dialogue_dir / ink_filename}")

    json_path = ink_path.with_suffix(".ink.json")
    globals_path = dialogue_dir / "globals.ink"
    custom_externals = load_custom_externals_definitions(dialogue_dir)
    source_path = ink_path
    temp_path = None

    if globals_path.exists() or custom_externals:
        include_path = (
            os.path.relpath(globals_path, start=ink_path.parent)
            if globals_path.exists()
            else None
        )
        with tempfile.NamedTemporaryFile(
            dir=ink_path.parent,
            suffix=".ink",
            delete=False,
            mode="w",
            encoding="utf-8",
        ) as temp_file:
            try:
                if include_path is not None:
                    temp_file.write(f"INCLUDE {include_path}\n")
                if custom_externals:
                    for name, arg_count in custom_externals.items():
                        args = ", ".join(f"arg{i}" for i in range(arg_count))
                        temp_file.write(f"EXTERNAL {name}({args})\n")
                temp_file.write(ink_path.read_text(encoding="utf-8"))
                temp_file.close()
                temp_path = Path(temp_file.name)
                source_path = temp_path

                result = subprocess.run(
                    ["inklecate", "-o", str(json_path), str(source_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
    else:
        result = subprocess.run(
            ["inklecate", "-o", str(json_path), str(source_path)],
            capture_output=True,
            text=True,
            check=False,
        )

    if result.returncode != 0:
        err_output = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
        match = re.search(r"line\s+(\d+)", err_output, re.IGNORECASE)
        line_no = int(match.group(1)) if match else 1
        ink_path_obj = find_ink_path(ink_filename, dialogue_dir)
        bad_code = ""
        if ink_path_obj and ink_path_obj.exists():
            lines = ink_path_obj.read_text(encoding="utf-8").splitlines()
            if 1 <= line_no <= len(lines):
                bad_code = lines[line_no - 1].strip()

        raise ValueError(
            f"Error compiling Ink file '{ink_filename}' at line {line_no}:\n"
            f"  Line {line_no}: {bad_code}\n"
            f"Diagnostics: {err_output}"
        )

    return json_path


def _collect_scenario_handles_from_list(node: list[Any], origin: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for index, element in enumerate(node):
        if isinstance(element, dict) and element.get("x()") == SCENARIO_FUNCTION:
            handle = _extract_scenario_handle_from_list(node, index)
            if handle is None:
                raise ValueError(
                    f"Could not determine scenario() filename from compiled JSON in knot '{origin}'"
                )
            results.append((origin, handle))
    return results


def _extract_scenario_handle_from_list(node: list[Any], index: int) -> str | None:
    for j in range(index - 1, -1, -1):
        elt = node[j]
        if isinstance(elt, str) and elt.startswith("^"):
            return elt[1:]
        if isinstance(elt, str) and elt in {"str", "pop", "ev", "/str", "/ev"}:
            continue
        if isinstance(elt, dict) and elt.get("x()") == SCENARIO_FUNCTION:
            continue
    return None


def _is_internal_target(target: str, knot_names: set[str]) -> bool:
    if target.startswith(INTERNAL_DIVERT_PREFIX) or "$(" in target or "$" in target:
        return True
    if target.startswith("^"):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)*", target):
        return True
    if "." in target:
        segments = target.split(".")
        if any(segment.startswith("$") for segment in segments):
            return True
        if segments[-1].isdigit() and segments[0] in knot_names:
            return True
    return False


def _find_divert_targets(node: Any, origin: str) -> tuple[set[str], list[tuple[str, str]]]:
    targets: set[str] = set()
    scenario_calls: list[tuple[str, str]] = []

    if isinstance(node, dict):
        if "->" in node:
            target = node["->"]
            if isinstance(target, str) and not target.startswith(INTERNAL_DIVERT_PREFIX) and target not in INTERNAL_TARGETS:
                targets.add(target)
        for value in node.values():
            child_targets, child_scenarios = _find_divert_targets(value, origin)
            targets.update(child_targets)
            scenario_calls.extend(child_scenarios)
    elif isinstance(node, list):
        scenario_calls.extend(_collect_scenario_handles_from_list(node, origin))
        for element in node:
            child_targets, child_scenarios = _find_divert_targets(element, origin)
            targets.update(child_targets)
            scenario_calls.extend(child_scenarios)
    return targets, scenario_calls


def _parse_scenario_outcomes(raw: Any, scenario_path: Path) -> dict[str, str]:
    if isinstance(raw, dict):
        mapping = raw
    elif isinstance(raw, list):
        mapping = {}
        for item in raw:
            if not isinstance(item, dict) or len(item) != 1:
                raise TypeError(
                    f"Invalid outcomes entry in {scenario_path}: expected a list of single-key maps"
                )
            key, value = next(iter(item.items()))
            mapping[key] = value
    else:
        raise TypeError(
            f"Invalid outcomes value in {scenario_path}: expected a mapping or list, got {type(raw).__name__}"
        )

    outcomes: dict[str, str] = {}
    for label, target in mapping.items():
        if not isinstance(label, str):
            raise TypeError(
                f"Invalid outcome label in {scenario_path}: expected string, got {type(label).__name__}"
            )
        if not isinstance(target, str):
            raise TypeError(
                f"Invalid outcome target for '{label}' in {scenario_path}: expected string, got {type(target).__name__}"
            )
        outcomes[label] = target
    return outcomes


def _extract_string_args_before(node: list[Any], index: int, count: int) -> list[str] | None:
    args: list[str] = []
    j = index - 1
    while j >= 0 and len(args) < count:
        if node[j] == "/str":
            if (
                j - 2 >= 0
                and node[j - 2] == "str"
                and isinstance(node[j - 1], str)
                and node[j - 1].startswith("^")
            ):
                args.append(node[j - 1][1:])
                j -= 3
                continue
        elif isinstance(node[j], str) and node[j].startswith("^"):
            args.append(node[j][1:])
            j -= 1
            continue
        elif isinstance(node[j], (int, float, bool)):
            args.append(str(node[j]))
            j -= 1
            continue
        j -= 1
    if len(args) == count:
        args.reverse()
        return args
    return None


def _extract_targets_from_branch(node: Any) -> set[str]:
    targets: set[str] = set()
    if isinstance(node, dict):
        if "->" in node:
            tgt = node["->"]
            if (
                isinstance(tgt, str)
                and not _is_internal_target(tgt, set())
                and tgt not in INTERNAL_TARGETS
                and tgt not in ("end", "done")
            ):
                targets.add(tgt)
        for val in node.values():
            targets.update(_extract_targets_from_branch(val))
    elif isinstance(node, list):
        for item in node:
            targets.update(_extract_targets_from_branch(item))
    return targets


def _extract_target_from_branch(branch_dict: Any) -> str | None:
    targets = _extract_targets_from_branch(branch_dict)
    if targets:
        return next(iter(targets))
    return None


def _find_dialogue_conditions(
    node: Any, origin: str
) -> tuple[list[tuple[str, str, bool]], list[tuple[str, str, str, bool]]]:
    get_results: list[tuple[str, str, bool]] = []
    has_results: list[tuple[str, str, str, bool]] = []
    if isinstance(node, list):
        for i, element in enumerate(node):
            if element == "ev":
                ev_idx = None
                for k in range(i + 1, len(node)):
                    if node[k] == "/ev":
                        ev_idx = k
                        break
                if ev_idx is not None:
                    block_gets: list[tuple[str, bool]] = []
                    block_hass: list[tuple[str, str, bool]] = []
                    for k in range(i + 1, ev_idx):
                        item = node[k]
                        if isinstance(item, dict):
                            fn = item.get("x()")
                            if fn == "get":
                                args = _extract_string_args_before(node, k, 1)
                                if args:
                                    negated = (k + 1 < ev_idx and node[k + 1] == "!")
                                    block_gets.append((args[0], negated))
                            elif fn == "has":
                                args = _extract_string_args_before(node, k, 2)
                                if args:
                                    negated = (k + 1 < ev_idx and node[k + 1] == "!")
                                    block_hass.append((args[0], args[1], negated))

                    total_conds = len(block_gets) + len(block_hass)
                    if total_conds > 0:
                        for k in range(ev_idx + 1, len(node)):
                            elt = node[k]
                            if isinstance(elt, list) and len(elt) >= 2:
                                first_item = elt[0]
                                second_item = elt[1]
                                if (
                                    isinstance(first_item, dict)
                                    and first_item.get("->") == ".^.b"
                                ):
                                    is_conditional = first_item.get("c") is True
                                    target_knots = _extract_targets_from_branch(second_item)
                                    for target_knot in target_knots:
                                        if is_conditional:
                                            for var_path, neg in block_gets:
                                                get_results.append((target_knot, var_path, neg))
                                            for list_path, item_name, neg in block_hass:
                                                has_results.append((target_knot, list_path, item_name, neg))
                                        elif total_conds == 1:
                                            for var_path, neg in block_gets:
                                                get_results.append((target_knot, var_path, not neg))
                                            for list_path, item_name, neg in block_hass:
                                                has_results.append((target_knot, list_path, item_name, not neg))
                                    if is_conditional and not target_knots:
                                        fallthrough_target = None
                                        for following in node[k + 1 :]:
                                            if isinstance(following, dict) and "->" in following:
                                                candidate = following["->"]
                                                if (
                                                    isinstance(candidate, str)
                                                    and not _is_internal_target(candidate, set())
                                                    and candidate not in INTERNAL_TARGETS
                                                ):
                                                    fallthrough_target = candidate
                                                    break
                                        if fallthrough_target is not None:
                                            for var_path, neg in block_gets:
                                                get_results.append(
                                                    (fallthrough_target, var_path, not neg)
                                                )
                                            for list_path, item_name, neg in block_hass:
                                                has_results.append(
                                                    (
                                                        fallthrough_target,
                                                        list_path,
                                                        item_name,
                                                        not neg,
                                                    )
                                                )
                                        else:
                                            has_content = any(
                                                isinstance(following, str)
                                                and following.startswith("^")
                                                for following in node[ev_idx + 1 :]
                                            )
                                            if has_content:
                                                content_target = (
                                                    f"__content__{origin}_{len(get_results) + len(has_results)}"
                                                )
                                                for var_path, neg in block_gets:
                                                    get_results.append(
                                                        (content_target, var_path, not neg)
                                                    )
                                                for list_path, item_name, neg in block_hass:
                                                    has_results.append(
                                                        (
                                                            content_target,
                                                            list_path,
                                                            item_name,
                                                            not neg,
                                                        )
                                                    )
                                    continue
                            if elt in ("nop", "done"):
                                break
            if isinstance(element, (list, dict)):
                g, h = _find_dialogue_conditions(element, origin)
                get_results.extend(g)
                has_results.extend(h)
    elif isinstance(node, dict):
        for val in node.values():
            g, h = _find_dialogue_conditions(val, origin)
            get_results.extend(g)
            has_results.extend(h)
    return get_results, has_results


def _find_get_conditions(node: Any, origin: str) -> list[tuple[str, str, bool]]:
    get_res, _ = _find_dialogue_conditions(node, origin)
    return get_res


def _find_list_mutations(node: Any, origin: str) -> list[tuple[str, str, bool]]:
    results: list[tuple[str, str, bool]] = []
    if isinstance(node, list):
        for i, element in enumerate(node):
            if isinstance(element, dict) and element.get("x()") in ("add", "remove"):
                is_add = element.get("x()") == "add"
                args = _extract_string_args_before(node, i, 2)
                if args is not None:
                    results.append((args[0], args[1], is_add))
            elif isinstance(element, (list, dict)):
                results.extend(_find_list_mutations(element, origin))
    elif isinstance(node, dict):
        for val in node.values():
            results.extend(_find_list_mutations(val, origin))
    return results


def _find_set_mutations(node: Any, origin: str) -> list[tuple[str, Any]]:
    results: list[tuple[str, Any]] = []
    if isinstance(node, list):
        for i, element in enumerate(node):
            if isinstance(element, dict) and element.get("x()") == "set":
                key = None
                value = None
                if i - 1 >= 0:
                    prev1 = node[i - 1]
                    if prev1 == "/str":
                        if i - 3 >= 0 and node[i - 3] == "str" and isinstance(node[i - 2], str) and node[i - 2].startswith("^"):
                            value = node[i - 2][1:]
                            if i - 6 >= 0 and node[i - 4] == "/str" and node[i - 6] == "str" and isinstance(node[i - 5], str) and node[i - 5].startswith("^"):
                                key = node[i - 5][1:]
                    else:
                        value = prev1
                        if i - 4 >= 0 and node[i - 2] == "/str" and node[i - 4] == "str" and isinstance(node[i - 3], str) and node[i - 3].startswith("^"):
                            key = node[i - 3][1:]
                if key is not None:
                    results.append((key, value))
            elif isinstance(element, (list, dict)):
                results.extend(_find_set_mutations(element, origin))
    elif isinstance(node, dict):
        for val in node.values():
            results.extend(_find_set_mutations(val, origin))
    return results


def _build_graph_from_story(
    story_data: dict[str, Any]
) -> tuple[
    dict[str, set[str]],
    list[tuple[str, str]],
    dict[str, list[tuple[str, str, bool]]],
    dict[str, list[tuple[str, Any]]],
    dict[str, list[tuple[str, str, str, bool]]],
    dict[str, list[tuple[str, str, bool]]],
]:
    if "root" not in story_data or not isinstance(story_data["root"], list):
        raise ValueError("Compiled Ink JSON did not contain a valid root element")

    root = story_data["root"]
    if len(root) < 3 or not isinstance(root[0], list):
        raise ValueError(f"Compiled Ink JSON root structure is malformed: full data {story_data}")

    knots_container = root[2] if isinstance(root[2], dict) else {}
    knots = set(knots_container.keys())
    graph: dict[str, set[str]] = {"__root__": set()}
    get_conditions: dict[str, list[tuple[str, str, bool]]] = {"__root__": []}
    has_conditions: dict[str, list[tuple[str, str, str, bool]]] = {"__root__": []}
    set_mutations: dict[str, list[tuple[str, Any]]] = {"__root__": []}
    list_mutations: dict[str, list[tuple[str, str, bool]]] = {"__root__": []}
    for knot in knots:
        graph[knot] = set()
        get_conditions[knot] = []
        has_conditions[knot] = []
        set_mutations[knot] = []
        list_mutations[knot] = []

    root_targets, root_scenarios = _find_divert_targets(root[0], "__root__")
    graph["__root__"].update(
        t for t in root_targets if t in knots or t in INTERNAL_TARGETS
    )
    root_gets, root_hass = _find_dialogue_conditions(root[0], "__root__")
    get_conditions["__root__"].extend(root_gets)
    has_conditions["__root__"].extend(root_hass)
    for target, _, _ in root_gets:
        if target.startswith("__content__"):
            graph["__root__"].add(target)
            graph[target] = set()
            get_conditions[target] = []
            has_conditions[target] = []
            set_mutations[target] = []
            list_mutations[target] = []
    for target, _, _, _ in root_hass:
        if target.startswith("__content__"):
            graph["__root__"].add(target)
            graph[target] = set()
            get_conditions[target] = []
            has_conditions[target] = []
            set_mutations[target] = []
            list_mutations[target] = []
    set_mutations["__root__"].extend(_find_set_mutations(root[0], "__root__"))
    list_mutations["__root__"].extend(_find_list_mutations(root[0], "__root__"))

    for knot_name, knot_body in knots_container.items():
        targets, scenario_calls = _find_divert_targets(knot_body, knot_name)
        graph[knot_name].update(
            t for t in targets if t in knots or t in INTERNAL_TARGETS
        )
        root_scenarios.extend(scenario_calls)
        knot_gets, knot_hass = _find_dialogue_conditions(knot_body, knot_name)
        get_conditions[knot_name].extend(knot_gets)
        has_conditions[knot_name].extend(knot_hass)
        for target, _, _ in knot_gets:
            if target.startswith("__content__"):
                graph[knot_name].add(target)
                graph[target] = set()
                get_conditions[target] = []
                has_conditions[target] = []
                set_mutations[target] = []
                list_mutations[target] = []
        for target, _, _, _ in knot_hass:
            if target.startswith("__content__"):
                graph[knot_name].add(target)
                graph[target] = set()
                get_conditions[target] = []
                has_conditions[target] = []
                set_mutations[target] = []
                list_mutations[target] = []
        set_mutations[knot_name].extend(_find_set_mutations(knot_body, knot_name))
        list_mutations[knot_name].extend(_find_list_mutations(knot_body, knot_name))

    return graph, root_scenarios, get_conditions, set_mutations, has_conditions, list_mutations


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
        elif context == "shop":
            pass
        else:
            raise ValueError(
                f"{dialogue_file}: unsupported scenario context '{context}' in '{scenario_path.relative_to(game_path)}'"
            )


def _collect_reachable_knots(graph: dict[str, set[str]]) -> set[str]:
    visited: set[str] = set()
    stack = ["__root__"]
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        for successor in graph.get(current, []):
            if successor not in visited:
                stack.append(successor)
    return visited


def analyze_ink_file(
    ink_filename: str, dialogue_dir: Path, game_path: Path | None = None
) -> tuple[
    dict[str, set[str]],
    list[tuple[str, str]],
    dict[str, list[tuple[str, str, bool]]],
    dict[str, list[tuple[str, Any]]],
    dict[str, list[tuple[str, str, str, bool]]],
    dict[str, list[tuple[str, str, bool]]],
]:
    json_path = ink_json_path(ink_filename, dialogue_dir)
    with open(json_path, encoding="utf-8") as f:
        story_data = json.load(f)

    (
        graph,
        scenario_calls,
        get_conditions,
        set_mutations,
        has_conditions,
        list_mutations,
    ) = _build_graph_from_story(story_data)
    if game_path is not None:
        ink_path = find_ink_path(ink_filename, dialogue_dir) or (dialogue_dir / ink_filename)
        _collect_scenario_graph_edges(graph, scenario_calls, game_path, ink_path)

    return (
        graph,
        scenario_calls,
        get_conditions,
        set_mutations,
        has_conditions,
        list_mutations,
    )
