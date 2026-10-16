from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

SCENARIO_FUNCTION = "scenario"
INTERNAL_DIVERT_PREFIX = "."
INTERNAL_TARGETS = {"done"}
PASS_MOVE_DESTINATION = "__pass_target_room__"
LOOT_ALL_ITEMS = "__loot_all_items__"


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


def _parse_ink_argument_before(
    node: list[Any], end_index: int
) -> tuple[Any, int] | None:
    if end_index <= 0:
        return None

    token_index = end_index - 1
    token = node[token_index]
    if isinstance(token, dict) and isinstance(token.get("x()"), str):
        function_name = token["x()"]
        arg_count = token.get("exArgs", 0)
        if not isinstance(arg_count, int) or arg_count < 0:
            return None
        args = _parse_ink_arguments_before(node, token_index, arg_count)
        if args is None:
            return None
        values, start_index = args
        return (function_name, values), start_index

    if token == "/str":
        if (
            token_index >= 2
            and node[token_index - 2] == "str"
            and isinstance(node[token_index - 1], str)
            and node[token_index - 1].startswith("^")
        ):
            return node[token_index - 1][1:], token_index - 2
        return None
    if isinstance(token, str) and token.startswith("^"):
        return token[1:], token_index
    if isinstance(token, (int, float, bool)):
        return token, token_index
    return None


def _parse_ink_arguments_before(
    node: list[Any], end_index: int, count: int
) -> tuple[list[Any], int] | None:
    args: list[Any] = []
    cursor = end_index
    for _ in range(count):
        parsed = _parse_ink_argument_before(node, cursor)
        if parsed is None:
            return None
        value, cursor = parsed
        args.append(value)
    args.reverse()
    return args, cursor


def _evaluate_ink_argument(
    argument: Any,
    origin: str,
    resolver: Callable[[str, list[Any], str], Any] | None,
) -> Any:
    if (
        isinstance(argument, tuple)
        and len(argument) == 2
        and isinstance(argument[0], str)
        and isinstance(argument[1], list)
    ):
        function_name, args = argument
        evaluated_args = [
            _evaluate_ink_argument(arg, origin, resolver) for arg in args
        ]
        if resolver is None:
            return None
        return resolver(function_name, evaluated_args, origin)
    return argument


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


def _evaluate_ev_block(
    tokens: list[Any],
    temp_vars: dict[str, Any] | None = None,
    switch_subject: Any = None,
) -> list[Any]:
    if temp_vars is None:
        temp_vars = {}
    stack: list[Any] = []
    if switch_subject is not None:
        stack.append(switch_subject)
    idx = 0
    while idx < len(tokens):
        item = tokens[idx]
        if item == "str":
            parts: list[str] = []
            idx += 1
            while idx < len(tokens) and tokens[idx] != "/str":
                part = tokens[idx]
                if isinstance(part, str) and part.startswith("^"):
                    parts.append(part[1:])
                elif isinstance(part, str):
                    parts.append(part)
                idx += 1
            stack.append("".join(parts))
        elif isinstance(item, (bool, int, float)):
            stack.append(item)
        elif isinstance(item, dict):
            if "x()" in item:
                fn = item["x()"]
                ex_args = item.get("exArgs", 1)
                popped: list[Any] = []
                for _ in range(min(ex_args, len(stack))):
                    popped.append(stack.pop())
                popped.reverse()
                if fn == "get" and len(popped) == 1:
                    stack.append(("get", popped[0]))
                elif fn == "has" and len(popped) == 2:
                    stack.append(("has", popped[0], popped[1]))
                elif fn == "set" and len(popped) == 2:
                    stack.append(("set", popped[0], popped[1]))
                elif fn == "increase" and len(popped) >= 1:
                    amount = popped[1] if len(popped) > 1 else 1
                    stack.append(("increase", popped[0], amount))
                else:
                    stack.append((fn, *popped))
            elif "VAR?" in item:
                vname = item["VAR?"]
                if vname in temp_vars:
                    stack.append(temp_vars[vname])
                else:
                    stack.append(("var", vname))
            elif "temp=" in item:
                if stack:
                    temp_vars[item["temp="]] = stack[-1]
            elif "VAR=" in item:
                if stack:
                    temp_vars[item["VAR="]] = stack[-1]
        elif item == "du":
            if stack:
                stack.append(stack[-1])
        elif item == "pop":
            if stack:
                stack.pop()
        elif item == "!":
            if stack:
                stack[-1] = ("not", stack[-1])
        elif item == "==":
            if len(stack) >= 2:
                b = stack.pop()
                a = stack.pop()
                if (
                    isinstance(a, tuple)
                    and len(a) == 3
                    and a[0] == "+"
                    and isinstance(a[1], tuple)
                    and a[1][0] == "get"
                    and isinstance(a[2], (int, float))
                    and isinstance(b, (int, float))
                ):
                    stack.append(("==", a[1], int(b - a[2])))
                elif (
                    isinstance(b, tuple)
                    and len(b) == 3
                    and b[0] == "+"
                    and isinstance(b[1], tuple)
                    and b[1][0] == "get"
                    and isinstance(b[2], (int, float))
                    and isinstance(a, (int, float))
                ):
                    stack.append(("==", b[1], int(a - b[2])))
                elif isinstance(b, tuple) and b[0] == "get":
                    stack.append(("==", b, a))
                else:
                    stack.append(("==", a, b))
        elif item == "!=":
            if len(stack) >= 2:
                b = stack.pop()
                a = stack.pop()
                stack.append(("!=", a, b))
        elif item in ("&&", "||"):
            if len(stack) >= 2:
                b = stack.pop()
                a = stack.pop()
                stack.append(("and" if item == "&&" else "or", a, b))
        elif item == "+":
            if len(stack) >= 2:
                b = stack.pop()
                a = stack.pop()
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    stack.append(a + b)
                elif isinstance(a, tuple) and a[0] == "get" and isinstance(b, (int, float)):
                    stack.append(("+", a, int(b)))
                elif isinstance(a, tuple) and a[0] == "+" and isinstance(b, (int, float)):
                    stack.append(("+", a[1], int(a[2] + b)))
                else:
                    stack.append(("+", a, b))
        elif item == "-":
            if len(stack) >= 2:
                b = stack.pop()
                a = stack.pop()
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    stack.append(a - b)
                elif isinstance(a, tuple) and a[0] == "get" and isinstance(b, (int, float)):
                    stack.append(("+", a, -int(b)))
                else:
                    stack.append(("-", a, b))
        idx += 1
    return stack


def _parse_boolean_expression(
    node: list[Any],
    start: int,
    end: int,
    temp_vars: dict[str, Any] | None = None,
    switch_subject: Any = None,
) -> Any | None:
    tokens = node[start:end]
    stack = _evaluate_ev_block(tokens, temp_vars=temp_vars, switch_subject=switch_subject)
    if stack:
        return stack[-1]
    return None


def _find_dialogue_conditions(
    node: Any,
    origin: str,
    temp_vars: dict[str, Any] | None = None,
    switch_subject: Any = None,
) -> tuple[
    list[tuple[str, str, bool]],
    list[tuple[str, str, str, bool]],
    list[tuple[str, Any]],
]:
    get_results: list[tuple[str, str, bool]] = []
    has_results: list[tuple[str, str, str, bool]] = []
    expression_results: list[tuple[str, Any]] = []
    if temp_vars is None:
        temp_vars = {}
    current_switch_subj = switch_subject

    if isinstance(node, list):
        pending_fallthrough: list[Any] = []
        skipped_branch_positions: set[int] = set()
        for i, element in enumerate(node):
            if i not in skipped_branch_positions and pending_fallthrough:
                if isinstance(element, dict) and "->" in element:
                    target = element["->"]
                    if (
                        isinstance(target, str)
                        and not _is_internal_target(target, {origin})
                        and target not in INTERNAL_TARGETS
                        and not target.startswith("__content__")
                    ):
                        expression_results.extend(
                            (target, expr) for expr in pending_fallthrough
                        )
                elif isinstance(element, list):
                    fallthrough_targets, _ = _find_divert_targets(
                        element, origin
                    )
                    expression_results.extend(
                        (target, expr)
                        for target in fallthrough_targets
                        if not _is_internal_target(target, {origin})
                        and target not in INTERNAL_TARGETS
                        and not target.startswith("__content__")
                        for expr in pending_fallthrough
                    )
            if element == "ev":
                ev_idx = None
                for k in range(i + 1, len(node)):
                    if node[k] == "/ev":
                        ev_idx = k
                        break
                if ev_idx is not None:
                    block_gets: list[tuple[str, bool]] = []
                    block_hass: list[tuple[str, str, bool]] = []
                    block_expression = _parse_boolean_expression(
                        node,
                        i + 1,
                        ev_idx,
                        temp_vars=temp_vars,
                        switch_subject=current_switch_subj,
                    )
                    # Check if this ev block is an assignment
                    is_assignment = False
                    for check_idx in range(ev_idx + 1, min(ev_idx + 3, len(node))):
                        nxt = node[check_idx]
                        if isinstance(nxt, dict) and ("temp=" in nxt or "VAR=" in nxt):
                            if "temp=" in nxt and block_expression is not None:
                                temp_vars[nxt["temp="]] = block_expression
                            if "VAR=" in nxt and block_expression is not None:
                                temp_vars[nxt["VAR="]] = block_expression
                            is_assignment = True
                            break
                        if isinstance(nxt, list) and nxt and nxt[0] == "du":
                            current_switch_subj = block_expression
                            break
                    if is_assignment:
                        continue

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

                    if (
                        block_expression is not None
                        and isinstance(block_expression, tuple)
                        and block_expression[0] == "=="
                        and isinstance(block_expression[1], tuple)
                        and block_expression[1][0] == "get"
                    ):
                        block_gets.append((block_expression[1][1], False))

                    total_conds = len(block_gets) + len(block_hass) + (1 if block_expression is not None else 0)
                    if total_conds > 0:
                        first_item = None
                        second_item = None
                        branch_pos = None
                        for k in range(ev_idx + 1, len(node)):
                            elt = node[k]
                            if (
                                isinstance(elt, list)
                                and len(elt) >= 2
                                and isinstance(elt[0], dict)
                                and elt[0].get("->") == ".^.b"
                            ):
                                first_item = elt[0]
                                second_item = elt[1]
                                branch_pos = k
                                break
                            elif (
                                isinstance(elt, dict)
                                and elt.get("->") == ".^.b"
                                and k + 1 < len(node)
                                and isinstance(node[k + 1], dict)
                                and "b" in node[k + 1]
                            ):
                                first_item = elt
                                second_item = node[k + 1]
                                branch_pos = k + 1
                                break
                            elif elt == "ev" or (isinstance(elt, list) and elt and elt[0] == "ev") or isinstance(elt, dict) and ("temp=" in elt or "VAR=" in elt) or elt in ("nop", "done"):
                                break

                        if first_item is not None and second_item is not None:
                            is_conditional = first_item.get("c") is True
                            target_knots = _extract_targets_from_branch(second_item)
                            if (
                                isinstance(second_item, dict)
                                and "b" in second_item
                                and isinstance(second_item["b"], list)
                            ):
                                for scenario_index, scenario_item in enumerate(second_item["b"]):
                                    if (
                                        isinstance(scenario_item, dict)
                                        and scenario_item.get("x()") == "scenario"
                                    ):
                                        args = _extract_string_args_before(second_item["b"], scenario_index, 1)
                                        if args:
                                            target_knots.add(f"__scenario__{args[0]}")
                            for target_knot in target_knots:
                                if is_conditional:
                                    if block_expression is not None:
                                        expression_results.append((target_knot, block_expression))
                                        expression_results.extend(
                                            (target_knot, expr)
                                            for expr in pending_fallthrough
                                        )
                                    for var_path, neg in block_gets:
                                        get_results.append((target_knot, var_path, neg))
                                    for list_path, item_name, neg in block_hass:
                                        has_results.append((target_knot, list_path, item_name, neg))
                                elif total_conds == 1:
                                    if block_expression is not None:
                                        expression_results.append((target_knot, ("not", block_expression)))
                                        expression_results.extend(
                                            (target_knot, expr)
                                            for expr in pending_fallthrough
                                        )
                                    for var_path, neg in block_gets:
                                        get_results.append((target_knot, var_path, not neg))
                                    for list_path, item_name, neg in block_hass:
                                        has_results.append((target_knot, list_path, item_name, not neg))

                            if is_conditional and not target_knots and branch_pos is not None:
                                fallthrough_target = None
                                for following in node[branch_pos + 1 :]:
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
                                    if block_expression is not None:
                                        expression_results.append(
                                            (
                                                fallthrough_target,
                                                ("not", block_expression),
                                            )
                                        )
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
                                        if block_expression is not None:
                                            expression_results.append(
                                                (
                                                    content_target,
                                                    ("not", block_expression),
                                                )
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
                            if is_conditional:
                                if branch_pos is not None:
                                    skipped_branch_positions.add(branch_pos)
                                    if (
                                        isinstance(node[branch_pos], dict)
                                        and node[branch_pos].get("->") == ".^.b"
                                    ):
                                        skipped_branch_positions.add(branch_pos - 1)
                                if block_expression is not None:
                                    pending_fallthrough.append(
                                        ("not", block_expression)
                                    )
            elif (
                isinstance(element, list)
                and element
                and element[0] == "du"
                and current_switch_subj is not None
            ):
                if "ev" in element and "/ev" in element:
                    e_start = element.index("ev")
                    e_end = element.index("/ev")
                    stk = _evaluate_ev_block(
                        element[e_start + 1 : e_end],
                        temp_vars=temp_vars,
                        switch_subject=current_switch_subj,
                    )
                    sw_expr = stk[-1] if stk else None
                    if sw_expr is not None:
                        for k in range(e_end + 1, len(element)):
                            elt = element[k]
                            if (
                                isinstance(elt, dict)
                                and elt.get("->") == ".^.b"
                                and k + 1 < len(element)
                            ):
                                tgts = _extract_targets_from_branch(element[k + 1])
                                for tgt in tgts:
                                    expression_results.append((tgt, sw_expr))
                                    if (
                                        isinstance(sw_expr, tuple)
                                        and sw_expr[0] == "=="
                                        and isinstance(sw_expr[1], tuple)
                                        and sw_expr[1][0] == "get"
                                    ):
                                        get_results.append((tgt, sw_expr[1][1], False))
            elif element == "pop":
                current_switch_subj = None

            if isinstance(element, (list, dict)):
                g, h, expressions = _find_dialogue_conditions(
                    element,
                    origin,
                    temp_vars=temp_vars,
                    switch_subject=current_switch_subj,
                )
                get_results.extend(g)
                has_results.extend(h)
                expression_results.extend(expressions)
    elif isinstance(node, dict):
        for val in node.values():
            g, h, expressions = _find_dialogue_conditions(
                val,
                origin,
                temp_vars=temp_vars,
                switch_subject=current_switch_subj,
            )
            get_results.extend(g)
            has_results.extend(h)
            expression_results.extend(expressions)
    return get_results, has_results, expression_results


def _find_get_conditions(node: Any, origin: str) -> list[tuple[str, str, bool]]:
    get_res, _, _ = _find_dialogue_conditions(node, origin)
    return get_res


def _collect_choice_bodies(node: Any) -> dict[str, list[Any]]:
    bodies: dict[str, list[Any]] = {}
    choice_targets: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    isinstance(key, str)
                    and re.fullmatch(r"c-\d+", key)
                    and isinstance(child, list)
                ):
                    bodies[key] = child
                    continue
                if key == "*" and isinstance(child, str):
                    choice_targets.add(child.rsplit(".", 1)[-1])
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(node)
    return {
        key: body
        for key, body in bodies.items()
        if key in choice_targets
    }


def _choice_sources(
    flow_name: str,
    graph: dict[str, set[str]],
    get_conditions: dict[str, list[tuple[str, str, bool]]],
    has_conditions: dict[str, list[tuple[str, str, str, bool]]],
    guard_expressions: dict[str, list[tuple[str, Any]]],
    flow_gets: list[tuple[str, str, bool]],
    flow_hass: list[tuple[str, str, str, bool]],
    flow_expressions: list[tuple[str, Any]],
    content_sources: set[str],
) -> set[str]:
    if content_sources:
        return content_sources

    internal_targets = {
        target
        for target, _, _ in flow_gets
        if _is_internal_target(target, set(graph)) or target in INTERNAL_TARGETS
    } | {
        target
        for target, _, _, _ in flow_hass
        if _is_internal_target(target, set(graph)) or target in INTERNAL_TARGETS
    } | {
        target
        for target, _ in flow_expressions
        if _is_internal_target(target, set(graph)) or target in INTERNAL_TARGETS
    }
    if not internal_targets:
        return {flow_name}

    gate = f"__content__{flow_name}_choice_gate"
    graph.setdefault(flow_name, set()).add(gate)
    graph.setdefault(gate, set())
    get_conditions.setdefault(gate, [])
    has_conditions.setdefault(gate, [])
    guard_expressions.setdefault(gate, [])
    get_flow_conditions = get_conditions.setdefault(flow_name, [])
    has_flow_conditions = has_conditions.setdefault(flow_name, [])
    expression_flow_conditions = guard_expressions.setdefault(flow_name, [])
    get_flow_conditions.extend(
        (gate, path, not negated)
        for target, path, negated in flow_gets
        if target in internal_targets
    )
    has_flow_conditions.extend(
        (gate, path, item, not negated)
        for target, path, item, negated in flow_hass
        if target in internal_targets
    )
    expression_flow_conditions.extend(
        (gate, ("not", expression))
        for target, expression in flow_expressions
        if target in internal_targets
    )
    return {gate}


def _find_list_mutations(
    node: Any,
    origin: str,
    external_argument_resolver: Callable[[str, list[Any], str], Any] | None = None,
    excluded_choice_keys: set[str] | None = None,
) -> list[tuple[str, str, bool]]:
    if excluded_choice_keys is None:
        excluded_choice_keys = set()
    results: list[tuple[str, str, bool]] = []
    if isinstance(node, list):
        for i, element in enumerate(node):
            if isinstance(element, dict) and element.get("x()") == "loot":
                results.append(("$self.inventory", LOOT_ALL_ITEMS, True))
            elif isinstance(element, dict) and element.get("x()") in ("add", "remove"):
                is_add = element.get("x()") == "add"
                parsed_args = _parse_ink_arguments_before(node, i, 2)
                if parsed_args is not None:
                    args, _ = parsed_args
                    list_path = args[0]
                    item_name = _evaluate_ink_argument(
                        args[1], origin, external_argument_resolver
                    )
                    if isinstance(list_path, str) and isinstance(item_name, str):
                        results.append((list_path, item_name, is_add))
            elif isinstance(element, (list, dict)):
                results.extend(
                    _find_list_mutations(
                        element,
                        origin,
                        external_argument_resolver,
                        excluded_choice_keys,
                    )
                )
    elif isinstance(node, dict):
        for key, val in node.items():
            if key in excluded_choice_keys:
                continue
            results.extend(
                _find_list_mutations(
                    val, origin, external_argument_resolver, excluded_choice_keys
                )
            )
    return results


def _find_set_mutations(
    node: Any, origin: str, excluded_choice_keys: set[str] | None = None
) -> list[tuple[str, Any]]:
    if excluded_choice_keys is None:
        excluded_choice_keys = set()
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
            elif isinstance(element, dict) and element.get("x()") == "increase":
                key = None
                amount = 1
                if i - 1 >= 0:
                    prev1 = node[i - 1]
                    if isinstance(prev1, (int, float)):
                        amount = int(prev1)
                        if i - 4 >= 0 and node[i - 2] == "/str" and node[i - 4] == "str" and isinstance(node[i - 3], str) and node[i - 3].startswith("^"):
                            key = node[i - 3][1:]
                    elif prev1 == "/str":
                        if i - 3 >= 0 and node[i - 3] == "str" and isinstance(node[i - 2], str) and node[i - 2].startswith("^"):
                            key = node[i - 2][1:]
                if key is not None:
                    results.append((key, ("+", amount)))
            elif isinstance(element, (list, dict)):
                results.extend(
                    _find_set_mutations(element, origin, excluded_choice_keys)
                )
    elif isinstance(node, dict):
        for key, val in node.items():
            if key in excluded_choice_keys:
                continue
            results.extend(
                _find_set_mutations(val, origin, excluded_choice_keys)
            )
    return results


def _find_move_mutations(
    node: Any, origin: str, excluded_choice_keys: set[str] | None = None
) -> list[tuple[str, str, str]]:
    if excluded_choice_keys is None:
        excluded_choice_keys = set()
    results: list[tuple[str, str, str]] = []
    if isinstance(node, list):
        for i, element in enumerate(node):
            if isinstance(element, dict):
                function_name = element.get("x()")
                if function_name == "move":
                    args = _extract_string_args_before(node, i, 3)
                    if args is not None:
                        results.append((args[0], args[1], args[2]))
                elif function_name == "pass":
                    results.append(
                        (
                            "$player",
                            "rooms.$current_room",
                            PASS_MOVE_DESTINATION,
                        )
                    )
            elif isinstance(element, (list, dict)):
                results.extend(
                    _find_move_mutations(element, origin, excluded_choice_keys)
                )
    elif isinstance(node, dict):
        for key, val in node.items():
            if key in excluded_choice_keys:
                continue
            results.extend(
                _find_move_mutations(val, origin, excluded_choice_keys)
            )
    return results


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
        raise ValueError(f"Compiled Ink JSON root structure is malformed: full data {story_data}")

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
        target
        for target, _, _ in root_gets
        if target.startswith("__content__")
    } | {
        target
        for target, _, _, _ in root_hass
        if target.startswith("__content__")
    }
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
        move_mutations[choice_target] = _find_move_mutations(
            choice_body, choice_target
        )
        guard_expressions.setdefault(choice_target, [])
    raw_root_sets = _find_set_mutations(
        root[0], "__root__", root_choice_keys
    )
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
                if var_name in temp_var_mutations and (var_name, expr[2] + 1) not in set_mutations.get(target, []):
                        set_mutations.setdefault(target, []).append((var_name, expr[2] + 1))
        fallthrough_targets = [
            t for t in graph["__root__"] if t not in {target for target, _ in root_expressions} and t in knots_container
        ]
        for ft in fallthrough_targets:
            for key, val in raw_root_sets:
                if isinstance(val, (int, str, bool)) and key in temp_var_mutations and (key, val) not in set_mutations.get(ft, []):
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
            target
            for target, _, _ in knot_gets
            if target.startswith("__content__")
        } | {
            target
            for target, _, _, _ in knot_hass
            if target.startswith("__content__")
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
            guard_expressions[stitch_name].extend(
                guard_expressions.get(knot_name, [])
            )

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
        move_mutations,
        guard_expressions,
    ) = _build_graph_from_story(story_data, external_argument_resolver)
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
        move_mutations,
        guard_expressions,
    )
