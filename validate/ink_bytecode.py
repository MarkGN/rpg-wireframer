from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from validate.ink_analyser_constants import (
    INTERNAL_DIVERT_PREFIX,
    INTERNAL_TARGETS,
    LOOT_ALL_ITEMS,
    PASS_MOVE_DESTINATION,
    SCENARIO_FUNCTION,
)


def _collect_scenario_handles_from_list(
    node: list[Any], origin: str
) -> list[tuple[str, str]]:
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


def _find_divert_targets(
    node: Any, origin: str
) -> tuple[set[str], list[tuple[str, str]]]:
    targets: set[str] = set()
    scenario_calls: list[tuple[str, str]] = []

    if isinstance(node, dict):
        if "->" in node:
            target = node["->"]
            if (
                isinstance(target, str)
                and not target.startswith(INTERNAL_DIVERT_PREFIX)
                and target not in INTERNAL_TARGETS
            ):
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


def _extract_string_args_before(
    node: list[Any], index: int, count: int
) -> list[str] | None:
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
        evaluated_args = [_evaluate_ink_argument(arg, origin, resolver) for arg in args]
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
                elif (
                    isinstance(a, tuple)
                    and a[0] == "get"
                    and isinstance(b, (int, float))
                ):
                    stack.append(("+", a, int(b)))
                elif (
                    isinstance(a, tuple) and a[0] == "+" and isinstance(b, (int, float))
                ):
                    stack.append(("+", a[1], int(a[2] + b)))
                else:
                    stack.append(("+", a, b))
        elif item == "-":
            if len(stack) >= 2:
                b = stack.pop()
                a = stack.pop()
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    stack.append(a - b)
                elif (
                    isinstance(a, tuple)
                    and a[0] == "get"
                    and isinstance(b, (int, float))
                ):
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
    stack = _evaluate_ev_block(
        tokens, temp_vars=temp_vars, switch_subject=switch_subject
    )
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
                    fallthrough_targets, _ = _find_divert_targets(element, origin)
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
                                    negated = k + 1 < ev_idx and node[k + 1] == "!"
                                    block_gets.append((args[0], negated))
                            elif fn == "has":
                                args = _extract_string_args_before(node, k, 2)
                                if args:
                                    negated = k + 1 < ev_idx and node[k + 1] == "!"
                                    block_hass.append((args[0], args[1], negated))

                    if (
                        block_expression is not None
                        and isinstance(block_expression, tuple)
                        and block_expression[0] == "=="
                        and isinstance(block_expression[1], tuple)
                        and block_expression[1][0] == "get"
                    ):
                        block_gets.append((block_expression[1][1], False))

                    total_conds = (
                        len(block_gets)
                        + len(block_hass)
                        + (1 if block_expression is not None else 0)
                    )
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
                            elif (
                                elt == "ev"
                                or (isinstance(elt, list) and elt and elt[0] == "ev")
                                or isinstance(elt, dict)
                                and ("temp=" in elt or "VAR=" in elt)
                                or elt in ("nop", "done")
                            ):
                                break

                        if first_item is not None and second_item is not None:
                            is_conditional = first_item.get("c") is True
                            target_knots = _extract_targets_from_branch(second_item)
                            if (
                                isinstance(second_item, dict)
                                and "b" in second_item
                                and isinstance(second_item["b"], list)
                            ):
                                for scenario_index, scenario_item in enumerate(
                                    second_item["b"]
                                ):
                                    if (
                                        isinstance(scenario_item, dict)
                                        and scenario_item.get("x()") == "scenario"
                                    ):
                                        args = _extract_string_args_before(
                                            second_item["b"], scenario_index, 1
                                        )
                                        if args:
                                            target_knots.add(f"__scenario__{args[0]}")
                            for target_knot in target_knots:
                                if is_conditional:
                                    if block_expression is not None:
                                        expression_results.append(
                                            (target_knot, block_expression)
                                        )
                                        expression_results.extend(
                                            (target_knot, expr)
                                            for expr in pending_fallthrough
                                        )
                                    for var_path, neg in block_gets:
                                        get_results.append((target_knot, var_path, neg))
                                    for list_path, item_name, neg in block_hass:
                                        has_results.append(
                                            (target_knot, list_path, item_name, neg)
                                        )
                                elif total_conds == 1:
                                    if block_expression is not None:
                                        expression_results.append(
                                            (target_knot, ("not", block_expression))
                                        )
                                        expression_results.extend(
                                            (target_knot, expr)
                                            for expr in pending_fallthrough
                                        )
                                    for var_path, neg in block_gets:
                                        get_results.append(
                                            (target_knot, var_path, not neg)
                                        )
                                    for list_path, item_name, neg in block_hass:
                                        has_results.append(
                                            (target_knot, list_path, item_name, not neg)
                                        )

                            if (
                                is_conditional
                                and not target_knots
                                and branch_pos is not None
                            ):
                                fallthrough_target = None
                                for following in node[branch_pos + 1 :]:
                                    if (
                                        isinstance(following, dict)
                                        and "->" in following
                                    ):
                                        candidate = following["->"]
                                        if (
                                            isinstance(candidate, str)
                                            and not _is_internal_target(
                                                candidate, set()
                                            )
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
                                        content_target = f"__content__{origin}_{len(get_results) + len(has_results)}"
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
    return {key: body for key, body in bodies.items() if key in choice_targets}


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

    internal_targets = (
        {
            target
            for target, _, _ in flow_gets
            if _is_internal_target(target, set(graph)) or target in INTERNAL_TARGETS
        }
        | {
            target
            for target, _, _, _ in flow_hass
            if _is_internal_target(target, set(graph)) or target in INTERNAL_TARGETS
        }
        | {
            target
            for target, _ in flow_expressions
            if _is_internal_target(target, set(graph)) or target in INTERNAL_TARGETS
        }
    )
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
                        if (
                            i - 3 >= 0
                            and node[i - 3] == "str"
                            and isinstance(node[i - 2], str)
                            and node[i - 2].startswith("^")
                        ):
                            value = node[i - 2][1:]
                            if (
                                i - 6 >= 0
                                and node[i - 4] == "/str"
                                and node[i - 6] == "str"
                                and isinstance(node[i - 5], str)
                                and node[i - 5].startswith("^")
                            ):
                                key = node[i - 5][1:]
                    else:
                        value = prev1
                        if (
                            i - 4 >= 0
                            and node[i - 2] == "/str"
                            and node[i - 4] == "str"
                            and isinstance(node[i - 3], str)
                            and node[i - 3].startswith("^")
                        ):
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
                        if (
                            i - 4 >= 0
                            and node[i - 2] == "/str"
                            and node[i - 4] == "str"
                            and isinstance(node[i - 3], str)
                            and node[i - 3].startswith("^")
                        ):
                            key = node[i - 3][1:]
                    elif prev1 == "/str":
                        if (
                            i - 3 >= 0
                            and node[i - 3] == "str"
                            and isinstance(node[i - 2], str)
                            and node[i - 2].startswith("^")
                        ):
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
            results.extend(_find_set_mutations(val, origin, excluded_choice_keys))
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
            results.extend(_find_move_mutations(val, origin, excluded_choice_keys))
    return results
