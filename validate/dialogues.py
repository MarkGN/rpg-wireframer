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
        raise ValueError(f"Expected mapping in {custom_path}, got {type(raw).__name__}")

    custom_externals: dict[str, int] = {}
    for name, spec in raw.items():
        if not isinstance(name, str):
            raise ValueError(f"Invalid custom external name {name!r} in {custom_path}")
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
        temp_file = tempfile.NamedTemporaryFile(
            dir=ink_path.parent,
            suffix=".ink",
            delete=False,
            mode="w",
            encoding="utf-8",
        )
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
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    else:
        result = subprocess.run(
            ["inklecate", "-o", str(json_path), str(source_path)],
            capture_output=True,
            text=True,
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
        if any(segment.startswith("$") or segment.startswith("^") for segment in segments):
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
            if isinstance(target, str) and not target.startswith(INTERNAL_DIVERT_PREFIX):
                if target not in INTERNAL_TARGETS:
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
                raise ValueError(
                    f"Invalid outcomes entry in {scenario_path}: expected a list of single-key maps"
                )
            key, value = next(iter(item.items()))
            mapping[key] = value
    else:
        raise ValueError(
            f"Invalid outcomes value in {scenario_path}: expected a mapping or list, got {type(raw).__name__}"
        )

    outcomes: dict[str, str] = {}
    for label, target in mapping.items():
        if not isinstance(label, str):
            raise ValueError(
                f"Invalid outcome label in {scenario_path}: expected string, got {type(label).__name__}"
            )
        if not isinstance(target, str):
            raise ValueError(
                f"Invalid outcome target for '{label}' in {scenario_path}: expected string, got {type(target).__name__}"
            )
        outcomes[label] = target
    return outcomes


def _build_graph_from_story(story_data: dict[str, Any]) -> tuple[dict[str, set[str]], list[tuple[str, str]]]:
    if "root" not in story_data or not isinstance(story_data["root"], list):
        raise ValueError("Compiled Ink JSON did not contain a valid root element")

    root = story_data["root"]
    if len(root) < 3 or not isinstance(root[0], list):
        raise ValueError(f"Compiled Ink JSON root structure is malformed: full data {story_data}")

    knots_container = root[2] if isinstance(root[2], dict) else {}
    knots = set(knots_container.keys())
    graph: dict[str, set[str]] = {"__root__": set()}
    for knot in knots:
        graph[knot] = set()

    root_targets, root_scenarios = _find_divert_targets(root[0], "__root__")
    graph["__root__"].update(
        t for t in root_targets if t in knots or t in INTERNAL_TARGETS
    )

    for knot_name, knot_body in knots_container.items():
        targets, scenario_calls = _find_divert_targets(knot_body, knot_name)
        graph[knot_name].update(
            t for t in targets if t in knots or t in INTERNAL_TARGETS
        )
        root_scenarios.extend(scenario_calls)

    return graph, root_scenarios


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
            raise ValueError(
                f"{dialogue_file}: scenario file '{scenario_path.relative_to(game_path)}' must contain a mapping"
            )
        context = raw.get("context")
        if not isinstance(context, str):
            raise ValueError(
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


def validate_dialogues(game_path: Path | str) -> None:
    game_path = Path(game_path)
    dialogue_dir = game_path / "dialogue"
    if not dialogue_dir.exists() or not dialogue_dir.is_dir():
        raise ValueError(f"Dialogue directory not found: {dialogue_dir}")

    ink_paths = sorted(dialogue_dir.rglob("*.ink"))
    if not ink_paths:
        raise ValueError(f"No Ink files found in {dialogue_dir}")

    for ink_path in ink_paths:
        if ink_path.name == "globals.ink":
            continue

        ink_filename = ink_path.name
        json_path = ink_json_path(ink_filename, dialogue_dir)
        with open(json_path, encoding="utf-8") as f:
            story_data = json.load(f)

        graph, scenario_calls = _build_graph_from_story(story_data)
        _collect_scenario_graph_edges(graph, scenario_calls, game_path, ink_path)

        all_knots = {name for name in graph if name != "__root__"}
        reachable = _collect_reachable_knots(graph)
        unreachable = sorted(all_knots - reachable)
        if unreachable:
            raise ValueError(
                f"{ink_path}: unreachable knots/stitches: {', '.join(unreachable)}"
            )

        # validate target existence after scenario edges are added
        target_errors: list[str] = []
        for origin, successors in graph.items():
            if origin == "__root__":
                continue
            for target in successors:
                if target not in all_knots and target not in INTERNAL_TARGETS:
                    if not _is_internal_target(target, all_knots):
                        target_errors.append(
                            f"{ink_path}: missing divert target '{target}' in knot '{origin}'"
                        )
        for target in graph["__root__"]:
            if target not in all_knots and target not in INTERNAL_TARGETS:
                if not _is_internal_target(target, all_knots):
                    target_errors.append(
                        f"{ink_path}: missing divert target '{target}' in root flow"
                    )
        if target_errors:
            raise ValueError("\n".join(target_errors))


if __name__ == "__main__":
    import sys

    validate_dialogues(Path(sys.argv[1]))
