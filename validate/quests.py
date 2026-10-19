from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path
from sys import argv
from time import monotonic
from typing import Any

import unified_planning.shortcuts as up
from unified_planning.engines.results import (
    LogLevel,
    LogMessage,
    PlanGenerationResult,
)
from unified_planning.io import PDDLWriter

up.get_environment().credits_stream = None
try:
    import up_fast_downward
except ImportError:
    up_fast_downward = None
from runners import world
from runners.binder import Binder
from validate.ink_analyser import (
    LOOT_ALL_ITEMS,
    PASS_MOVE_DESTINATION,
    _collect_reachable_knots,
    analyze_ink_file,
    find_ink_path,
)
from yaml_utils import load_yaml

_EXPANDED_NODE_PATTERN = re.compile(
    r"\bExpanded\s+([\d,]+)\s+(?:states?|state\(s\))(?=\W|$)", re.IGNORECASE
)
_FD_PHASE_TIME_PATTERN = re.compile(
    r"^\s*(translator|preprocessor|search)\s+(?:time|runtime)\s*:\s*"
    r"([\d.]+)\s*(?:s|sec(?:onds?)?)\b",
    re.IGNORECASE | re.MULTILINE,
)
_FD_DIAGNOSTIC_LINE_PATTERN = re.compile(
    r"\b(?:translator|preprocessor|search)\s+(?:time|runtime)\s*:"
    r"|\bRunning\s+(?:translator|preprocessor|search)\b"
    r"|\b(?:expanded|generated|evaluated|peak memory|plan length)\b",
    re.IGNORECASE,
)


class _FastDownwardTimeout(TimeoutError):
    def __init__(self, output: str, elapsed: float):
        super().__init__(output)
        self.output = output
        self.elapsed = elapsed


def _expanded_node_count(result: Any) -> int | None:
    """Read an expanded-node count from planner metrics or captured logs."""
    metrics = getattr(result, "metrics", None)
    if isinstance(metrics, dict):
        for key, value in metrics.items():
            normalized_key = str(key).lower().replace(" ", "_").replace("-", "_")
            if normalized_key in {"expanded_nodes", "nodes_expanded"}:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass

    counts: list[int] = []
    for log in getattr(result, "log_messages", ()) or ():
        message = getattr(log, "message", log)
        for match in _EXPANDED_NODE_PATTERN.finditer(str(message)):
            counts.append(int(match.group(1).replace(",", "")))
    return sum(counts) if counts else None


def _planner_output(result: Any | None, captured_output: str = "") -> str:
    """Combine captured planner output with Unified Planning's logger output."""
    messages = [captured_output.strip()] if captured_output.strip() else []
    if result is not None:
        for log in getattr(result, "log_messages", ()) or ():
            message = getattr(log, "message", log)
            if message and str(message).strip():
                messages.append(str(message).strip())

    # The output stream and UP log messages can contain overlapping lines. Keep
    # their original order while avoiding duplicate diagnostics in the report.
    lines: list[str] = []
    seen: set[str] = set()
    for message in messages:
        for line in message.splitlines():
            normalized = line.strip()
            if normalized and normalized not in seen:
                lines.append(line)
                seen.add(normalized)
    return "\n".join(lines)


def _fast_downward_phase_times(
    output: str,
) -> dict[str, float]:
    """Extract phase times that Fast Downward reports in its own output."""
    phase_times: dict[str, float] = {}
    for phase, seconds in _FD_PHASE_TIME_PATTERN.findall(output):
        try:
            phase_times[phase.lower()] = float(seconds)
        except ValueError:
            continue
    return phase_times


def _fast_downward_diagnostic_lines(output: str) -> list[str]:
    return [
        line.strip()
        for line in output.splitlines()
        if line.strip() and _FD_DIAGNOSTIC_LINE_PATTERN.search(line)
    ]


def _sas_quest_goal_values(
    sas_task: str, quest_fluent_names: dict[str, str]
) -> dict[str, tuple[int, int]]:
    """Find each quest's positive SAS variable/value in the translated task."""
    lines = sas_task.splitlines()
    fluent_to_quest = {
        re.sub(r"[^a-z0-9]", "", pddl_name.lower()): quest_id
        for quest_id, pddl_name in quest_fluent_names.items()
    }
    assignments: dict[str, tuple[int, int]] = {}
    variable_blocks = [
        index for index, line in enumerate(lines) if line == "begin_variable"
    ]
    if not variable_blocks:
        raise ValueError("Fast Downward output has no SAS variable section")

    for start in variable_blocks:
        if start + 3 >= len(lines):
            continue
        variable_match = re.fullmatch(r"var(\d+)", lines[start + 1])
        try:
            value_count = int(lines[start + 3])
        except ValueError:
            continue
        if variable_match is None:
            continue
        variable = int(variable_match.group(1))
        for value, line in enumerate(lines[start + 4 : start + 4 + value_count]):
            if not line.startswith("Atom "):
                continue
            normalized_line = re.sub(r"[^a-z0-9]", "", line.lower())
            for fluent, quest_id in fluent_to_quest.items():
                if fluent and fluent in normalized_line:
                    assignments[quest_id] = (variable, value)
                    break

    return assignments


def _sas_task_with_goal(
    sas_task: str, assignment: tuple[int, int]
) -> str:
    """Return a SAS task copy whose goal is one positive quest fluent."""
    lines = sas_task.splitlines()
    try:
        start = lines.index("begin_goal")
        end = lines.index("end_goal", start)
    except ValueError as error:
        raise ValueError("Fast Downward output has no SAS goal section") from error
    variable, value = assignment
    lines[start : end + 1] = ["begin_goal", "1", f"{variable} {value}", "end_goal"]
    return "\n".join(lines) + "\n"


def _run_fast_downward_command(
    command: list[str], cwd: Path, timeout: float | None
) -> tuple[str, int, float]:
    """Run a Fast Downward driver command and return its output, code, and time."""
    started = monotonic()
    process_options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **process_options,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.kill()
        output, _ = process.communicate()
        if not output and error.output:
            output = (
                error.output.decode(errors="replace")
                if isinstance(error.output, bytes)
                else error.output
            )
        raise _FastDownwardTimeout(output, monotonic() - started) from error
    return output, process.returncode, monotonic() - started


def _solve_fast_downward_quests(
    problem: Any,
    quest_completed: dict[str, Any],
    quest_ids: list[str],
    planner: Any,
    timeout_seconds: float | None = None,
) -> tuple[dict[str, dict[str, Any]], float, str | None]:
    """Translate quest goals once, then run searches with individual SAS goals."""
    if not quest_ids:
        return {}, 0.0, None

    problem.clear_goals()
    goals = [quest_completed[quest_id] for quest_id in quest_ids]
    # Keep every quest fluent relevant to translation without requiring all
    # quests to be jointly achievable. A conjunctive all-quests goal can be
    # proven unsolvable by the translator, which then emits only a dummy SAS
    # task and discards the individual quest variables we need for reuse.
    problem.add_goal(goals[0] if len(goals) == 1 else up.Or(*goals))
    writer = PDDLWriter(problem)
    records: dict[str, dict[str, Any]] = {}
    deadline = (
        monotonic() + timeout_seconds if timeout_seconds is not None else None
    )

    def run_command(command: list[str], working_dir: Path) -> tuple[str, int, float]:
        remaining = None if deadline is None else max(0.0, deadline - monotonic())
        if remaining is not None and remaining <= 0:
            raise _FastDownwardTimeout("Quest validation deadline reached", 0.0)
        return _run_fast_downward_command(command, working_dir, remaining)

    with tempfile.TemporaryDirectory(prefix="quest-fast-downward-") as temp_name:
        temp_dir = Path(temp_name)
        domain_path = temp_dir / "domain.pddl"
        problem_path = temp_dir / "problem.pddl"
        sas_path = temp_dir / "output.sas"
        writer.write_domain(str(domain_path))
        writer.write_problem(str(problem_path))

        base_command = planner._base_cmd(str(temp_dir / "plan.txt"))
        translate_command = base_command + [
            "--translate",
            str(domain_path),
            str(problem_path),
        ]
        try:
            translation_output, return_code, translation_seconds = (
                run_command(translate_command, temp_dir)
            )
        except _FastDownwardTimeout as error:
            first_quest = quest_ids[0]
            records[first_quest] = {
                "result": None,
                "output": error.output,
                "translation_seconds": error.elapsed,
                "search_seconds": 0.0,
                "timeout": True,
            }
            return records, 0.0, first_quest

        if return_code != 0 or not sas_path.exists():
            raise RuntimeError(
                "Fast Downward translation failed:\n" + translation_output
            )
        sas_task = sas_path.read_text(encoding="utf-8")
        goal_values = _sas_quest_goal_values(
            sas_task,
            {
                quest_id: writer.get_pddl_name(quest_completed[quest_id])
                for quest_id in quest_ids
            },
        )
        search_config = (
            [planner._fd_search_config]
            if planner._fd_search_config
            else ["eager_greedy([ff()])"]
        )

        for index, quest_id in enumerate(quest_ids):
            if quest_id not in goal_values:
                # Fast Downward removes a goal fluent when its value is
                # unreachable in the grounded task. It cannot be searched in
                # SAS, and is already known to be unsolvable from this state.
                records[quest_id] = {
                    "result": None,
                    "output": "Fast Downward proved quest goal unreachable during translation.",
                    "translation_seconds": translation_seconds if index == 0 else 0.0,
                    "search_seconds": 0.0,
                    "timeout": False,
                    "goal_pruned": True,
                }
                continue
            plan_path = temp_dir / f"plan-{index}.txt"
            quest_sas_path = temp_dir / f"task-{index}.sas"
            quest_sas_path.write_text(
                _sas_task_with_goal(sas_task, goal_values[quest_id]),
                encoding="utf-8",
            )
            command = planner._base_cmd(str(plan_path)) + [
                str(quest_sas_path),
                "--search-options",
                "--search",
                *search_config,
            ]
            try:
                search_output, return_code, search_seconds = run_command(
                    command, temp_dir
                )
            except _FastDownwardTimeout as error:
                records[quest_id] = {
                    "result": None,
                    "output": error.output,
                    "translation_seconds": translation_seconds if index == 0 else 0.0,
                    "search_seconds": error.elapsed,
                    "timeout": True,
                }
                return records, translation_seconds, quest_id

            plan = None
            if plan_path.exists():
                plan = planner._plan_from_file(
                    problem, str(plan_path), writer.get_item_named
                )
            log_messages = [LogMessage(LogLevel.INFO, search_output)]
            status = planner._result_status(
                problem, plan, return_code, log_messages
            )
            result = PlanGenerationResult(
                status,
                plan=plan,
                engine_name=planner.name,
                log_messages=log_messages,
                metrics={"engine_internal_time": str(search_seconds)},
            )
            records[quest_id] = {
                "result": result,
                "output": (
                    translation_output + "\n" + search_output
                    if index == 0
                    else search_output
                ),
                "translation_seconds": translation_seconds if index == 0 else 0.0,
                "search_seconds": search_seconds,
                "timeout": False,
            }
    return records, translation_seconds, None


class _Profile:
    def __init__(self, limit_seconds: float = 120.0):
        self.started = monotonic()
        self.deadline = self.started + limit_seconds
        self.limit_seconds = limit_seconds
        self.phase_seconds: dict[str, float] = {}
        self.solver_calls = 0
        self.solver_seconds = 0.0
        self.expanded_nodes = 0
        self.expanded_node_results = 0
        self.expanded_node_unavailable = 0
        self.stopped = False
        self.stop_reason = ""
        self.planner_name = ""
        self.solver_records: list[dict[str, Any]] = []

    def expired(self) -> bool:
        if monotonic() >= self.deadline:
            self.stopped = True
            self.stop_reason = "two-minute profiling limit reached"
            return True
        return False

    def remaining(self) -> float:
        return max(0.0, self.deadline - monotonic())

    def add_time(self, phase: str, seconds: float) -> None:
        self.phase_seconds[phase] = self.phase_seconds.get(phase, 0.0) + seconds

    def report(
        self, problem: Any | None = None, state_example: list[str] | None = None, verbose: bool = False
    ):
        elapsed = monotonic() - self.started
        measured = sum(self.phase_seconds.values())
        self.phase_seconds["Other"] = max(0.0, elapsed - measured)
        print("\nQuest validator profile")
        print(f"Elapsed: {elapsed:.2f}s")
        if self.stopped:
            print(f"Stopped: {self.stop_reason}")
        print(f"Solver calls: {self.solver_calls}")
        if self.expanded_node_results:
            print(
                f"Expanded nodes: {self.expanded_nodes:,} across "
                f"{self.expanded_node_results} solver results"
            )
        else:
            print("Expanded nodes: unavailable")
        if self.expanded_node_unavailable:
            print(
                "Expanded-node count unavailable for "
                f"{self.expanded_node_unavailable} solver call(s)"
            )
        if self.planner_name:
            print(f"Planner: {self.planner_name}")
        print(f"Planner solve time (within search): {self.solver_seconds:.2f}s")
        print("Time by phase:")
        for phase, seconds in self.phase_seconds.items():
            fraction = seconds / elapsed if elapsed else 0.0
            print(f"  {phase}: {seconds:.2f}s ({fraction:.1%})")
        slow_records = [
            record for record in self.solver_records if record["seconds"] >= 10.0
        ]
        if slow_records:
            print("Solver calls taking at least 10s:")
            for record in sorted(
                slow_records, key=lambda item: item["seconds"], reverse=True
            ):
                print(
                    f"  {record['goal']}: {record['seconds']:.2f}s "
                    f"({record['status']})"
                    + (
                        f", {record['expanded_nodes']:,} expanded"
                        if record.get("expanded_nodes") is not None
                        else ""
                    )
                )
        if self.solver_records:
            print("Slowest solver calls:")
            for record in sorted(
                self.solver_records,
                key=lambda item: item["seconds"],
                reverse=True,
            )[:10]:
                print(
                    f"  {record['goal']}: {record['seconds']:.2f}s "
                    f"({record['status']})"
                    + (
                        f", {record['expanded_nodes']:,} expanded"
                        if record.get("expanded_nodes") is not None
                        else ""
                    )
                )
        fd_records = [
            record for record in self.solver_records if record.get("fd_output")
        ]
        if fd_records:
            print("Fast Downward output by solver call:")
            for record in fd_records:
                phase_times = record.get("fd_phase_times", {})
                reported_times = _fast_downward_phase_times(record["fd_output"])
                phase_labels = []
                for phase in ("translator", "preprocessor", "search"):
                    if phase == "translator" and record.get("fd_translation_reused"):
                        phase_labels.append("translator: reused")
                    elif phase in phase_times:
                        if phase in reported_times:
                            phase_labels.append(f"{phase}: {phase_times[phase]:.2f}s")
                        else:
                            phase_labels.append(
                                f"{phase}: ~{phase_times[phase]:.2f}s (measured)"
                            )
                    elif phase == "preprocessor":
                        phase_labels.append("preprocessor: not run")
                    else:
                        phase_labels.append(f"{phase}: not reported")
                phase_summary = ", ".join(phase_labels)
                print(f"  {record['goal']}: {phase_summary}")
                for line in _fast_downward_diagnostic_lines(record["fd_output"]):
                    print(f"    {line}")
        if problem is not None:
            fluents = list(problem.fluents)
            actions = list(problem.actions)
            objects = list(problem.all_objects)
            print(
                "State/model size: "
                f"{len(fluents)} fluents, {len(actions)} actions, {len(objects)} objects"
            )
            boolean_fluents = [fluent for fluent in fluents if not fluent.signature]
            state_count = (
                f"{2 ** len(boolean_fluents):,}"
                if len(boolean_fluents) < 1000
                else "too large to materialize"
            )
            print(
                "Estimated boolean state space: "
                f"2^{len(boolean_fluents)} ({state_count} states)"
            )
            if verbose:
                print("Example actions:")
                for action in actions[:10]:
                    print(f"  {action.name}")
        if state_example and verbose:
            print("Example initial state:")
            for fact in state_example[:30]:
                print(f"  {fact}")


def _planner_names() -> list[str] | None:
    if up_fast_downward is not None:
        return ["fast-downward"]
    return None


def _load_craft_recipes(game_path: Path) -> list[dict[str, Any]]:
    """Load crafting recipes from scenario files, filtering to actual craft contexts."""
    recipes: list[dict[str, Any]] = []
    scenario_dir = game_path / "world" / "scenarios"
    if not scenario_dir.exists():
        scenario_dir = game_path / "scenarios"

    for scenario_path in sorted(scenario_dir.glob("*.yaml")):
        data = load_yaml(scenario_path)
        if not isinstance(data, dict):
            continue
        if data.get("context") != "craft":
            continue
        recipe_ref = data.get("recipes")
        if not isinstance(recipe_ref, str):
            continue
        recipes_path = game_path / f"{recipe_ref}.yaml"
        if not recipes_path.exists():
            recipes_path = scenario_dir / f"{recipe_ref}.yaml"
        if not recipes_path.exists():
            continue
        raw = load_yaml(recipes_path)
        if isinstance(raw, dict):
            raw_recipes = raw.get("recipes", [])
        else:
            raw_recipes = []
        if isinstance(raw_recipes, list):
            recipes.extend(recipe for recipe in raw_recipes if isinstance(recipe, dict))

    fallback_path = game_path / "recipes.yaml"
    if not recipes and fallback_path.exists():
        raw = load_yaml(fallback_path)
        if isinstance(raw, dict):
            raw_recipes = raw.get("recipes", [])
            if isinstance(raw_recipes, list):
                recipes.extend(
                    recipe for recipe in raw_recipes if isinstance(recipe, dict)
                )

    return recipes


def _load_craft_scenarios(game_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Map each craft scenario name to the recipe list it exposes."""
    scenarios: dict[str, list[dict[str, Any]]] = {}
    scenario_dir = game_path / "world" / "scenarios"
    if not scenario_dir.exists():
        scenario_dir = game_path / "scenarios"
    if not scenario_dir.exists():
        return scenarios

    for scenario_path in sorted(scenario_dir.glob("*.yaml")):
        data = load_yaml(scenario_path)
        if not isinstance(data, dict) or data.get("context") != "craft":
            continue
        recipe_ref = data.get("recipes")
        if not isinstance(recipe_ref, str):
            continue
        recipes_path = game_path / f"{recipe_ref}.yaml"
        if not recipes_path.exists():
            recipes_path = scenario_dir / f"{recipe_ref}.yaml"
        if not recipes_path.exists():
            continue
        raw = load_yaml(recipes_path)
        raw_recipes = raw.get("recipes", []) if isinstance(raw, dict) else []
        scenarios[scenario_path.stem] = [
            recipe for recipe in raw_recipes if isinstance(recipe, dict)
        ]

    fallback_path = game_path / "recipes.yaml"
    if not scenarios and fallback_path.exists():
        raw = load_yaml(fallback_path)
        raw_recipes = raw.get("recipes", []) if isinstance(raw, dict) else []
        scenarios["craft"] = [
            recipe for recipe in raw_recipes if isinstance(recipe, dict)
        ]
    return scenarios


def _craft_rooms_for_game(
    objects: dict[str, Any], rooms: dict[str, Any], game_path: Path
) -> set[str]:
    """Only allow crafting in rooms whose object is wired to a craft scenario."""
    scenario_dir = game_path / "world" / "scenarios"
    if not scenario_dir.exists():
        scenario_dir = game_path / "scenarios"
    if not scenario_dir.exists():
        return set()

    craft_rooms: set[str] = set()
    for room_id, room_data in rooms.items():
        for object_id in room_data.get("objects", []):
            object_data = objects.get(object_id, {})
            ink_ref = object_data.get(
                "ink", object_data.get("dialogue", f"{object_id}.ink")
            )
            if not isinstance(ink_ref, str):
                continue
            scenario_name = Path(ink_ref).stem
            scenario_path = scenario_dir / f"{scenario_name}.yaml"
            if not scenario_path.exists():
                continue
            raw = load_yaml(scenario_path)
            if not isinstance(raw, dict) or raw.get("context") != "craft":
                continue
            craft_rooms.add(room_id)
    return craft_rooms


def _bind_var_path(var_path: str, npc_id: str, w: world.World) -> str:
    npc_room = ""
    try:
        npc_room = w.find_npc(npc_id)
    except SystemExit:
        pass
    return Binder(
        {
            "player": w.player_handle,
            "self": npc_id,
            "current_room": w.current_room,
            "npc_room": npc_room,
        }
    ).apply(var_path)


def _evaluate_initial_state(bound_path: str, w: world.World) -> bool:
    try:
        val = w.get_state(bound_path)
        return bool(val)
    except (KeyError, IndexError, TypeError):
        return False


def _evaluate_has_initial_state(bound_list: str, item: str, w: world.World) -> bool:
    try:
        val = w.get_state(bound_list)
        if isinstance(val, (list, tuple, set)):
            return item in val
        return False
    except (KeyError, IndexError, TypeError):
        return False


def _discrete_value_key(value: Any) -> tuple[str, Any] | None:
    if isinstance(value, bool):
        return ("number", int(value))
    if isinstance(value, (int, float)):
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    if value is None:
        return ("none", None)
    return None


def validate_quests(game_path: Path | str, *, profile: bool = False, verbose: bool = False) -> list[str]:
    """Validate that every declared quest can reach a truthy completion mutation."""
    game_path = Path(game_path)
    profiler = _Profile() if profile else None
    world_load_started = monotonic()
    w = world.World(game_path)
    rooms = w.world_state["rooms"]
    objects = w.world_state["objects"]
    player_handle = w.player_handle
    start_room = w.current_room
    dialogue_dir = game_path / "dialogue"
    quest_ids = sorted(w.world_state.get("quests", {}))
    quest_targets = {quest_id: f"quests.{quest_id}.completed" for quest_id in quest_ids}
    if profiler:
        profiler.add_time("World loading (YAML)", monotonic() - world_load_started)

    def resolve_bound_path(var_path: str, npc_id: str) -> str:
        key = (var_path, npc_id)
        if key not in bound_cache:
            bound_cache[key] = _bind_var_path(var_path, npc_id, w)
        return bound_cache[key]

    bound_cache: dict[tuple[str, str], str] = {}

    def resolve_inventory_item(item: Any, npc_id: str) -> str | None:
        if isinstance(item, tuple) and len(item) == 2 and item[0] == "get":
            item = item[1]
        if isinstance(item, str) and item.startswith("$"):
            try:
                item = w.get_state(resolve_bound_path(item, npc_id))
            except (KeyError, IndexError, TypeError):
                return None
        return item if isinstance(item, str) else None

    # Map NPC dialogues
    dialogue_started = monotonic()
    npc_dialogue_graphs: dict[str, dict[str, set[str]]] = {}
    npc_get_conditions: dict[str, dict[str, list[tuple[str, str, bool]]]] = {}
    npc_set_mutations: dict[str, dict[str, list[tuple[str, Any]]]] = {}
    npc_has_conditions: dict[str, dict[str, list[tuple[str, str, str, bool]]]] = {}
    npc_list_mutations: dict[str, dict[str, list[tuple[str, str, bool]]]] = {}
    npc_move_mutations: dict[str, dict[str, list[tuple[str, str, str]]]] = {}
    npc_scenario_calls: dict[str, dict[str, set[str]]] = {}
    npc_guard_expressions: dict[str, dict[str, list[tuple[str, Any]]]] = {}

    for obj_id, obj_data in objects.items():
        if obj_id == player_handle:
            continue
        ink_ref = obj_data.get("ink", obj_data.get("dialogue", f"{obj_id}.ink"))
        if isinstance(ink_ref, str):
            ink_ref = ink_ref.removesuffix(".ink")
            ink_file = find_ink_path(f"{ink_ref}.ink", dialogue_dir)
            if ink_file and ink_file.exists():
                try:

                    def resolve_external_argument(
                        function_name: str, args: list[Any], _origin: str, id=obj_id
                    ) -> Any:
                        if (
                            function_name == "get"
                            and len(args) == 1
                            and isinstance(args[0], str)
                        ):
                            return w.get_state(resolve_bound_path(args[0], id))
                        return None

                    (
                        graph,
                        scenario_calls,
                        get_conds,
                        set_muts,
                        has_conds,
                        list_muts,
                        move_muts,
                        guard_expressions,
                    ) = analyze_ink_file(
                        f"{ink_ref}.ink",
                        dialogue_dir,
                        game_path,
                        resolve_external_argument,
                        profiler.phase_seconds if profiler else None,
                    )
                    npc_dialogue_graphs[obj_id] = graph
                    npc_get_conditions[obj_id] = get_conds
                    npc_set_mutations[obj_id] = set_muts
                    npc_has_conditions[obj_id] = has_conds
                    npc_list_mutations[obj_id] = list_muts
                    npc_move_mutations[obj_id] = move_muts
                    npc_guard_expressions[obj_id] = guard_expressions
                    by_origin: dict[str, set[str]] = {}
                    for origin, script in scenario_calls:
                        by_origin.setdefault(origin, set()).add(script)
                    npc_scenario_calls[obj_id] = by_origin
                except (OSError, ValueError, TypeError):
                    pass

    static_unreachable_knots: list[str] = []
    stateful_npc_dialogues: dict[str, dict[str, set[str]]] = {}
    relevant_knots_by_npc: dict[str, set[str]] = {}
    for npc_id, graph in npc_dialogue_graphs.items():
        reachable_knots = _collect_reachable_knots(graph)
        relevant_knots_by_npc[npc_id] = reachable_knots

        cond_map = npc_get_conditions.get(npc_id, {})
        mut_map = npc_set_mutations.get(npc_id, {})
        has_map = npc_has_conditions.get(npc_id, {})
        list_map = npc_list_mutations.get(npc_id, {})
        move_map = npc_move_mutations.get(npc_id, {})
        dyn = (
            any(
                bool(cond_list)
                for knot_name, cond_list in cond_map.items()
                if knot_name in reachable_knots
            )
            or any(
                bool(mut_list)
                for knot_name, mut_list in mut_map.items()
                if knot_name in reachable_knots
            )
            or any(
                bool(has_list)
                for knot_name, has_list in has_map.items()
                if knot_name in reachable_knots
            )
            or any(
                bool(list_list)
                for knot_name, list_list in list_map.items()
                if knot_name in reachable_knots
            )
            or any(
                bool(move_list)
                for knot_name, move_list in move_map.items()
                if knot_name in reachable_knots
            )
            or any(
                bool(scripts)
                for knot_name, scripts in npc_scenario_calls.get(npc_id, {}).items()
                if knot_name in reachable_knots
            )
        )
        if not dyn:
            unreachable = sorted(set(graph) - reachable_knots)
            static_unreachable_knots.extend(f"{npc_id}:{knot}" for knot in unreachable)
            continue
        stateful_npc_dialogues[npc_id] = graph
    player_inv_path = resolve_bound_path("$player.inventory", player_handle)

    def exit_destination(room_data: dict[str, Any], target: str) -> str | None:
        exits = room_data.get("exits", {})
        exit_data = exits.get(target) if isinstance(exits, dict) else None
        if isinstance(exit_data, dict):
            return exit_data.get("room", target)
        if isinstance(exit_data, str):
            return exit_data
        return target if target in rooms else None

    def guard_matches(guard: str, target: str, destination: str | None) -> bool:
        if guard == target or guard == destination:
            return True
        if destination in rooms:
            return guard == rooms[destination].get("name")
        return False

    def resolve_move_destination(destination: str, npc_id: str) -> str | None:
        bound_destination = resolve_bound_path(destination, npc_id)
        if bound_destination.startswith("rooms."):
            room_id = bound_destination.removeprefix("rooms.")
            return room_id if room_id in rooms else None
        if bound_destination.startswith("objects."):
            room_id = bound_destination.removeprefix("objects.")
            if room_id in rooms:
                return room_id
        if bound_destination in rooms:
            return bound_destination
        if destination in rooms:
            return destination
        return None

    def move_targets_player(target: str, npc_id: str) -> bool:
        return resolve_bound_path(target, npc_id) in {
            player_handle,
            f"objects.{player_handle}",
        }

    movement_interceptors: dict[tuple[str, str], str] = {}
    movement_accost_interceptors: set[tuple[str, str]] = set()
    movement_accost_paths: set[str] = set()
    for source, room_data in rooms.items():
        exits = room_data.get("exits", {})
        if not isinstance(exits, dict):
            continue
        source_objects = room_data.get("objects", [])
        for target, exit_data in exits.items():
            destination = exit_destination(room_data, target)
            if destination not in rooms:
                continue
            interceptor = (
                exit_data.get("blocker") if isinstance(exit_data, dict) else None
            )
            if interceptor is None:
                for object_id in source_objects:
                    object_data = objects.get(object_id, {})
                    guards = object_data.get("guards_exits", [])
                    if isinstance(guards, str):
                        guards = [guards]
                    elif isinstance(guards, dict):
                        guards = list(guards)
                    if any(
                        isinstance(guard, str)
                        and guard_matches(guard, target, destination)
                        for guard in guards
                    ):
                        interceptor = object_id
                        break
            if interceptor is None:
                for object_id in rooms[destination].get("objects", []):
                    if objects.get(object_id, {}).get("accosts", False):
                        interceptor = object_id
                        movement_accost_interceptors.add((source, destination))
                        movement_accost_paths.add(
                            resolve_bound_path(f"{object_id}.accosts", object_id)
                        )
                        break
            if interceptor is not None:
                movement_interceptors[(source, destination)] = interceptor

    for npc_id in movement_interceptors.values():
        if npc_id in npc_dialogue_graphs:
            stateful_npc_dialogues[npc_id] = npc_dialogue_graphs[npc_id]
            relevant_knots_by_npc[npc_id] = _collect_reachable_knots(
                npc_dialogue_graphs[npc_id]
            )

    if profiler:
        dialogue_elapsed = monotonic() - dialogue_started
        measured_ink = profiler.phase_seconds.get(
            "Ink compilation", 0.0
        ) + profiler.phase_seconds.get("Dialogue analysis", 0.0)
        profiler.add_time("Dialogue setup", max(0.0, dialogue_elapsed - measured_ink))

    # Construct STRIPS Planning Problem using unified-planning.
    # We now prune to only state variables that can actually affect reachability
    # in the reachable dialogue subgraph, so the planner sees only relevant state.
    model_preparation_started = monotonic()
    relevant_var_paths: set[str] = set()
    relevant_list_paths: set[tuple[str, str]] = set()
    finite_guard_paths: set[str] = set()
    discrete_values_by_path: dict[str, set[tuple[str, Any]]] = {}

    def collect_expression_values(expression: Any, npc_id: str) -> None:
        if not isinstance(expression, tuple) or not expression:
            return
        operator = expression[0]
        if operator in ("==", "!=") and len(expression) == 3:
            left, right = expression[1], expression[2]
            if isinstance(left, tuple) and len(left) == 2 and left[0] == "get":
                value_key = _discrete_value_key(right)
                bound_path = resolve_bound_path(left[1], npc_id)
                relevant_var_paths.add(bound_path)
                finite_guard_paths.add(bound_path)
                if value_key is not None:
                    discrete_values_by_path.setdefault(bound_path, set()).add(value_key)
            if isinstance(right, tuple) and len(right) == 2 and right[0] == "get":
                value_key = _discrete_value_key(left)
                bound_path = resolve_bound_path(right[1], npc_id)
                relevant_var_paths.add(bound_path)
                finite_guard_paths.add(bound_path)
                if value_key is not None:
                    discrete_values_by_path.setdefault(bound_path, set()).add(value_key)
        for child in expression[1:]:
            collect_expression_values(child, npc_id)

    for npc_id, graph in npc_dialogue_graphs.items():
        relevant = relevant_knots_by_npc.get(npc_id, set())
        if not relevant:
            continue
        for knot_name, cond_list in npc_get_conditions.get(npc_id, {}).items():
            if knot_name not in relevant:
                continue
            for _, var_path, _ in cond_list:
                relevant_var_paths.add(resolve_bound_path(var_path, npc_id))
        for knot_name, mut_list in npc_set_mutations.get(npc_id, {}).items():
            if knot_name not in relevant:
                continue
            for var_path, _ in mut_list:
                relevant_var_paths.add(resolve_bound_path(var_path, npc_id))
        for knot_name, has_list in npc_has_conditions.get(npc_id, {}).items():
            if knot_name not in relevant:
                continue
            for _, list_path, item_name, _ in has_list:
                resolved_item = resolve_inventory_item(item_name, npc_id)
                if resolved_item is not None:
                    relevant_list_paths.add(
                        (resolve_bound_path(list_path, npc_id), resolved_item)
                    )
        for knot_name, list_list in npc_list_mutations.get(npc_id, {}).items():
            if knot_name not in relevant:
                continue
            for list_path, item_name, _ in list_list:
                if item_name == LOOT_ALL_ITEMS:
                    bound_list = resolve_bound_path(list_path, npc_id)
                    try:
                        loot_items = w.get_state(bound_list)
                    except (KeyError, IndexError, TypeError):
                        loot_items = []
                    if isinstance(loot_items, list):
                        for loot_item in loot_items:
                            if isinstance(loot_item, str):
                                relevant_list_paths.add((bound_list, loot_item))
                                relevant_list_paths.add((player_inv_path, loot_item))
                else:
                    relevant_list_paths.add(
                        (resolve_bound_path(list_path, npc_id), item_name)
                    )
        for knot_name, expressions in npc_guard_expressions.get(npc_id, {}).items():
            if knot_name not in relevant:
                continue
            for _, expression in expressions:
                collect_expression_values(expression, npc_id)
    for npc_id, mutations_by_knot in npc_set_mutations.items():
        relevant = relevant_knots_by_npc.get(npc_id, set())
        for knot_name, mutations in mutations_by_knot.items():
            if knot_name not in relevant:
                continue
            for var_path, value in mutations:
                bound_path = resolve_bound_path(var_path, npc_id)
                value_key = _discrete_value_key(value)
                if value_key is not None and bound_path in finite_guard_paths:
                    discrete_values_by_path.setdefault(bound_path, set()).add(value_key)
    relevant_var_paths.update(movement_accost_paths)

    craft_scenarios = _load_craft_scenarios(game_path)
    craft_recipes = [
        recipe for recipes in craft_scenarios.values() for recipe in recipes
    ]
    relevant_inventory_items = {
        item_name
        for bound_path, item_name in relevant_list_paths
        if bound_path == player_inv_path
    }
    relevant_recipe_items: set[str] = set()
    if craft_recipes:
        for recipe in craft_recipes:
            recipe_items = [
                str(item)
                for item in list(recipe.get("input", []))
                + list(recipe.get("output", []))
            ]
            if any(item in relevant_inventory_items for item in recipe_items):
                relevant_recipe_items.update(recipe_items)
        relevant_list_paths.update(
            (player_inv_path, item_name) for item_name in sorted(relevant_recipe_items)
        )

    quest_set_candidates: dict[str, list[tuple[str, str]]] = {
        quest_id: [] for quest_id in quest_ids
    }
    for npc_id, mutations_by_knot in npc_set_mutations.items():
        relevant = relevant_knots_by_npc.get(npc_id, set())
        for knot_name, mutations in mutations_by_knot.items():
            if knot_name not in relevant:
                continue
            for path, value in mutations:
                for quest_id, target_path in quest_targets.items():
                    if path == target_path and bool(value):
                        quest_set_candidates[quest_id].append((npc_id, knot_name))

    if profiler:
        profiler.add_time(
            "Planning model preparation", monotonic() - model_preparation_started
        )
    state_construction_started = monotonic()
    problem = up.Problem("quest_reachability")

    Location = up.UserType("Location")
    Knot = up.UserType("Knot")
    NPC = up.UserType("NPC")

    at_room = up.Fluent("at_room", l=Location)
    pending_move = up.Fluent("pending_move", l=Location)
    at_knot = up.Fluent("at_knot", npc=NPC, k=Knot)
    in_explore = up.Fluent("in_explore")
    in_dialogue = up.Fluent("in_dialogue", npc=NPC)
    quest_completed: dict[str, Any] = {}

    problem.add_fluent(at_room, default_initial_value=False)
    problem.add_fluent(pending_move, default_initial_value=False)
    problem.add_fluent(at_knot, default_initial_value=False)
    problem.add_fluent(in_explore, default_initial_value=True)
    problem.add_fluent(in_dialogue, default_initial_value=False)
    for index, quest_id in enumerate(quest_ids):
        fluent = up.Fluent(f"quest_{index}_completed")
        problem.add_fluent(fluent, default_initial_value=False)
        quest_completed[quest_id] = fluent

    def add_completion_effects(action: Any, mutations: list[tuple[str, Any]]) -> None:
        for path, value in mutations:
            for quest_id, target_path in quest_targets.items():
                if path == target_path and bool(value):
                    action.add_effect(quest_completed[quest_id], True)

    def add_move_effects(
        action: Any, mutations: list[tuple[str, str, str]], npc_id: str
    ) -> None:
        for target, _, destination in mutations:
            if not move_targets_player(target, npc_id):
                continue
            if destination == PASS_MOVE_DESTINATION:
                continue
            destination_room = resolve_move_destination(destination, npc_id)
            if destination_room is None:
                continue
            for room in room_objs.values():
                action.add_effect(at_room(room), False)
            action.add_effect(at_room(room_objs[destination_room]), True)

    def add_pass_effects(action: Any, npc_id: str) -> None:
        for (source, destination), interceptor in movement_interceptors.items():
            if interceptor != npc_id:
                continue
            condition = pending_move(room_objs[destination])
            for room in room_objs.values():
                action.add_effect(at_room(room), False, condition=condition)
            action.add_effect(
                at_room(room_objs[destination]), True, condition=condition
            )
            action.add_effect(pending_move(room_objs[destination]), False)

    # Collect all bound variables for reachable get & set actions only.
    all_bound_vars = relevant_var_paths

    var_fluents_true: dict[str, Any] = {}
    var_fluents_false: dict[str, Any] = {}
    for idx, bound_var in enumerate(sorted(all_bound_vars)):
        fl_true = up.Fluent(f"var_{idx}_true")
        fl_false = up.Fluent(f"var_{idx}_false")
        problem.add_fluent(fl_true, default_initial_value=False)
        problem.add_fluent(fl_false, default_initial_value=True)
        init_val = _evaluate_initial_state(bound_var, w)
        problem.set_initial_value(fl_true, init_val)
        problem.set_initial_value(fl_false, not init_val)
        var_fluents_true[bound_var] = fl_true
        var_fluents_false[bound_var] = fl_false

    discrete_value_fluents: dict[tuple[str, tuple[str, Any]], Any] = {}
    binary_numeric_value_paths: set[str] = set()
    for bound_path, value_keys in sorted(discrete_values_by_path.items()):
        try:
            initial_value_key = _discrete_value_key(w.get_state(bound_path))
        except (KeyError, IndexError, TypeError):
            initial_value_key = None
        if initial_value_key is not None:
            value_keys.add(initial_value_key)
        if value_keys.issubset({("number", 0), ("number", 1)}):
            binary_numeric_value_paths.add(bound_path)
            continue
        for value_key in sorted(value_keys, key=repr):
            fluent_index = len(discrete_value_fluents)
            value_fluent = up.Fluent(f"var_value_{fluent_index}")
            problem.add_fluent(value_fluent, default_initial_value=False)
            problem.set_initial_value(
                value_fluent(),
                value_key == initial_value_key,
            )
            discrete_value_fluents[(bound_path, value_key)] = value_fluent

    # Collect bound list-item pairs for reachable has/add/remove actions only.
    all_bound_has_items: set[tuple[str, str]] = set(relevant_list_paths)

    # Also register items in rooms that the player can pick up, but only if they are
    # relevant to a reachable guard or mutation.
    for r_data in rooms.values():
        for item in r_data.get("items", []):
            if (player_inv_path, item) in relevant_list_paths:
                all_bound_has_items.add((player_inv_path, item))

    has_fluents_true: dict[tuple[str, str], Any] = {}
    has_fluents_false: dict[tuple[str, str], Any] = {}
    for idx, (bound_list, item) in enumerate(sorted(all_bound_has_items)):
        fl_true = up.Fluent(f"has_{idx}_true")
        fl_false = up.Fluent(f"has_{idx}_false")
        problem.add_fluent(fl_true, default_initial_value=False)
        problem.add_fluent(fl_false, default_initial_value=True)
        init_has = _evaluate_has_initial_state(bound_list, item, w)
        problem.set_initial_value(fl_true, init_has)
        problem.set_initial_value(fl_false, not init_has)
        has_fluents_true[(bound_list, item)] = fl_true
        has_fluents_false[(bound_list, item)] = fl_false

    def to_planning_expression(expression: Any, npc_id: str) -> Any | None:
        if not isinstance(expression, tuple) or not expression:
            return None
        operator = expression[0]
        if operator == "get" and len(expression) == 2:
            bound_var = resolve_bound_path(expression[1], npc_id)
            return (
                var_fluents_true[bound_var]() if bound_var in var_fluents_true else None
            )
        if operator == "has" and len(expression) == 3:
            bound_list = resolve_bound_path(expression[1], npc_id)
            item_name = resolve_inventory_item(expression[2], npc_id)
            if item_name is None:
                return None
            key = (bound_list, item_name)
            return has_fluents_true[key]() if key in has_fluents_true else None
        if operator in ("==", "!=") and len(expression) == 3:
            left, right = expression[1], expression[2]
            get_operand = None
            compared_value = None
            if isinstance(left, tuple) and len(left) == 2 and left[0] == "get":
                get_operand, compared_value = left, right
            elif isinstance(right, tuple) and len(right) == 2 and right[0] == "get":
                get_operand, compared_value = right, left
            if get_operand is None:
                return None
            value_key = _discrete_value_key(compared_value)
            bound_var = resolve_bound_path(get_operand[1], npc_id)
            value_fluent = (
                discrete_value_fluents.get((bound_var, value_key))
                if value_key is not None
                else None
            )
            if (
                value_fluent is None
                and bound_var in binary_numeric_value_paths
                and value_key == ("number", 0)
                and bound_var in var_fluents_false
            ):
                return var_fluents_false[bound_var]()
            if (
                value_fluent is None
                and bound_var in binary_numeric_value_paths
                and value_key == ("number", 1)
                and bound_var in var_fluents_true
            ):
                return var_fluents_true[bound_var]()
            if value_fluent is None:
                return None
            result = value_fluent()
            return result if operator == "==" else up.Not(result)
        if operator == "not" and len(expression) == 2:
            child = to_planning_expression(expression[1], npc_id)
            return up.Not(child) if child is not None else None
        if operator in ("and", "or") and len(expression) == 3:
            left = to_planning_expression(expression[1], npc_id)
            right = to_planning_expression(expression[2], npc_id)
            if left is None or right is None:
                return None
            return up.And(left, right) if operator == "and" else up.Or(left, right)
        return None

    def add_set_effects(
        action: Any, mutations: list[tuple[str, Any]], npc_id: str
    ) -> None:
        for var_path, value in mutations:
            bound_var = resolve_bound_path(var_path, npc_id)
            if bound_var in var_fluents_true:
                bool_value = bool(value)
                action.add_effect(var_fluents_true[bound_var], bool_value)
                action.add_effect(var_fluents_false[bound_var], not bool_value)
            value_key = _discrete_value_key(value)
            if value_key is None:
                continue
            for (
                candidate_path,
                candidate_key,
            ), fluent in discrete_value_fluents.items():
                if candidate_path == bound_var:
                    action.add_effect(fluent, candidate_key == value_key)

    def add_list_mutation_effects(
        action: Any,
        mutations: list[tuple[str, str, bool]],
        npc_id: str,
    ) -> None:
        for list_path, item_name, is_add in mutations:
            bound_list = resolve_bound_path(list_path, npc_id)
            if item_name == LOOT_ALL_ITEMS:
                try:
                    loot_items = w.get_state(bound_list)
                except (KeyError, IndexError, TypeError):
                    loot_items = []
                if isinstance(loot_items, list):
                    for loot_item in loot_items:
                        if not isinstance(loot_item, str):
                            continue
                        source_key = (bound_list, loot_item)
                        player_key = (player_inv_path, loot_item)
                        if source_key in has_fluents_true:
                            action.add_effect(has_fluents_true[source_key], False)
                            action.add_effect(has_fluents_false[source_key], True)
                        if player_key in has_fluents_true:
                            action.add_effect(has_fluents_true[player_key], True)
                            action.add_effect(has_fluents_false[player_key], False)
                continue

            key = (bound_list, item_name)
            if key not in has_fluents_true:
                continue
            if not is_add and bound_list == player_inv_path:
                action.add_precondition(has_fluents_true[key])
            action.add_effect(has_fluents_true[key], is_add)
            action.add_effect(has_fluents_false[key], not is_add)

    # Add room objects
    room_objs: dict[str, Any] = {}
    for r_name in rooms:
        r_obj = up.Object(r_name, Location)
        problem.add_object(r_obj)
        room_objs[r_name] = r_obj

    # Add initial location
    if start_room in room_objs:
        problem.set_initial_value(at_room(room_objs[start_room]), True)

    if profiler:
        profiler.add_time(
            "Planning state construction", monotonic() - state_construction_started
        )
    action_generation_started = monotonic()
    # Add room item pickups (take actions)
    for r_name, r_data in rooms.items():
        if r_name not in room_objs:
            continue
        for item in r_data.get("items", []):
            item_fl = up.Fluent(f"item_in_{r_name}_{item}")
            problem.add_fluent(item_fl, default_initial_value=True)
            take_act = up.InstantaneousAction(f"take_{r_name}_{item}")
            take_act.add_precondition(at_room(room_objs[r_name]))
            take_act.add_precondition(in_explore)
            take_act.add_precondition(item_fl)
            take_act.add_effect(item_fl, False)
            player_inv_key = (player_inv_path, item)
            if player_inv_key in has_fluents_true:
                take_act.add_effect(has_fluents_true[player_inv_key], True)
                take_act.add_effect(has_fluents_false[player_inv_key], False)
            problem.add_action(take_act)
    # Crafting is only available after a dialogue triggers a craft scenario, and the
    # scenario must be reachable in the room's object dialogue stack. This mirrors
    # runtime behavior: a lab only becomes a crafting bench if the dialogue actually
    # calls ~scenario("lab").
    craft_item_names = {
        item_name
        for bound_path, item_name in all_bound_has_items
        if bound_path == player_inv_path
    }
    scenario_fluents: dict[str, Any] = {}
    for scenario_name in sorted(craft_scenarios):
        fl = up.Fluent(f"scenario_{scenario_name}_active")
        problem.add_fluent(fl, default_initial_value=False)
        scenario_fluents[scenario_name] = fl

    craft_rooms_by_scenario: dict[str, set[str]] = {
        script: set() for script in craft_scenarios
    }
    for room_name, room_data in rooms.items():
        for object_id in room_data.get("objects", []):
            scenario_scripts = set()
            for origin_scripts in npc_scenario_calls.get(object_id, {}).values():
                scenario_scripts.update(origin_scripts)
            for script_name in scenario_scripts & set(craft_scenarios):
                craft_rooms_by_scenario.setdefault(script_name, set()).add(room_name)

    for script_name, recipes in craft_scenarios.items():
        for index, recipe in enumerate(recipes):
            recipe_items = [
                str(item)
                for item in list(recipe.get("input", []))
                + list(recipe.get("output", []))
            ]
            if not recipe_items:
                continue
            if not any(item in craft_item_names for item in recipe_items):
                continue
            inputs = [str(item) for item in recipe.get("input", [])]
            outputs = [str(item) for item in recipe.get("output", [])]
            for room_name in sorted(craft_rooms_by_scenario.get(script_name, set())):
                action_name = f"craft_{script_name}_{index}_{room_name}_{'_'.join(sorted(set(inputs + outputs)))}"
                craft_act = up.InstantaneousAction(action_name)
                craft_act.add_precondition(scenario_fluents[script_name])
                craft_act.add_precondition(at_room(room_objs[room_name]))
                craft_act.add_precondition(in_explore)
                for item in inputs:
                    key = (player_inv_path, item)
                    if key in has_fluents_true:
                        craft_act.add_precondition(has_fluents_true[key])
                for item in inputs:
                    key = (player_inv_path, item)
                    if key in has_fluents_true:
                        craft_act.add_effect(has_fluents_true[key], False)
                        craft_act.add_effect(has_fluents_false[key], True)
                for item in outputs:
                    key = (player_inv_path, item)
                    if key in has_fluents_true:
                        craft_act.add_effect(has_fluents_true[key], True)
                        craft_act.add_effect(has_fluents_false[key], False)
                problem.add_action(craft_act)

    # Add room transitions (move actions)
    for r_name, r_data in rooms.items():
        if r_name not in room_objs:
            continue
        exits = r_data.get("exits", [])
        raw_next_rooms = exits.values() if isinstance(exits, dict) else exits
        next_rooms = [
            nxt.get("room", nxt) if isinstance(nxt, dict) else nxt
            for nxt in raw_next_rooms
        ]
        for nxt in next_rooms:
            if nxt in room_objs:
                move_act = up.InstantaneousAction(f"move_{r_name}_to_{nxt}")
                move_act.add_precondition(at_room(room_objs[r_name]))
                move_act.add_precondition(in_explore)
                interceptor = movement_interceptors.get((r_name, nxt))
                if interceptor is not None:
                    if (r_name, nxt) in movement_accost_interceptors:
                        accost_path = resolve_bound_path(
                            f"{interceptor}.accosts", interceptor
                        )
                        move_act.add_precondition(var_fluents_false[accost_path])
                    else:
                        continue
                move_act.add_effect(at_room(room_objs[r_name]), False)
                move_act.add_effect(at_room(room_objs[nxt]), True)
                problem.add_action(move_act)
    # Add NPC and Dialogue objects & actions
    all_npc_knots: dict[str, list[str]] = {}
    knot_objects_by_npc: dict[str, dict[str, Any]] = {}
    for npc_id, graph in stateful_npc_dialogues.items():
        npc_obj = up.Object(npc_id, NPC)
        problem.add_object(npc_obj)

        knot_objs: dict[str, Any] = {}
        all_npc_knots[npc_id] = [k for k in graph if k != "__root__"]
        for knot_name in graph:
            k_obj = up.Object(f"{npc_id}_{knot_name}", Knot)
            problem.add_object(k_obj)
            knot_objs[knot_name] = k_obj
        knot_objects_by_npc[npc_id] = knot_objs

        npc_room = ""
        try:
            npc_room = w.find_npc(npc_id)
        except SystemExit:
            pass
        if not npc_room:
            npc_room = objects.get(npc_id, {}).get("location")

        if npc_room in room_objs:
            talk_act = up.InstantaneousAction(f"talk_{npc_id}")
            talk_act.add_precondition(in_explore)
            has_guarded_scenario = any(
                any(target.startswith("__scenario__") for target, _, _ in conds)
                for conds in npc_get_conditions.get(npc_id, {}).values()
            ) or any(
                any(target.startswith("__scenario__") for target, _, _, _ in conds)
                for conds in npc_has_conditions.get(npc_id, {}).values()
            )
            if not has_guarded_scenario and npc_room in room_objs:
                talk_act.add_precondition(at_room(room_objs[npc_room]))
            talk_act.add_effect(in_explore, False)
            talk_act.add_effect(in_dialogue(npc_obj), True)
            talk_act.add_effect(at_knot(npc_obj, knot_objs["__root__"]), True)
            add_set_effects(
                talk_act,
                npc_set_mutations.get(npc_id, {}).get("__root__", []),
                npc_id,
            )
            add_completion_effects(
                talk_act, npc_set_mutations.get(npc_id, {}).get("__root__", [])
            )
            # Apply list mutations from __root__
            add_list_mutation_effects(
                talk_act,
                npc_list_mutations.get(npc_id, {}).get("__root__", []),
                npc_id,
            )
            add_move_effects(
                talk_act, npc_move_mutations.get(npc_id, {}).get("__root__", []), npc_id
            )
            problem.add_action(talk_act)

    for npc_id, graph in stateful_npc_dialogues.items():
        npc_obj = problem.object(npc_id)
        knot_objs = {
            knot_name: problem.object(f"{npc_id}_{knot_name}") for knot_name in graph
        }
        get_conds = npc_get_conditions.get(npc_id, {})
        set_muts = npc_set_mutations.get(npc_id, {})
        has_conds = npc_has_conditions.get(npc_id, {})
        list_muts = npc_list_mutations.get(npc_id, {})
        move_muts = npc_move_mutations.get(npc_id, {})
        guard_expressions = npc_guard_expressions.get(npc_id, {})
        for src_knot, targets in graph.items():
            if src_knot not in knot_objs:
                continue
            src_conds = get_conds.get(src_knot, [])
            src_hass = has_conds.get(src_knot, [])
            for tgt_knot in targets:
                if tgt_knot in knot_objs:
                    branch_act = up.InstantaneousAction(
                        f"branch_{npc_id}_{src_knot}_to_{tgt_knot}"
                    )
                    branch_act.add_precondition(in_dialogue(npc_obj))
                    branch_act.add_precondition(at_knot(npc_obj, knot_objs[src_knot]))
                    branch_act.add_effect(at_knot(npc_obj, knot_objs[src_knot]), False)
                    branch_act.add_effect(at_knot(npc_obj, knot_objs[tgt_knot]), True)
                    if tgt_knot.startswith("__scenario__"):
                        script_name = tgt_knot.removeprefix("__scenario__")
                        if script_name in scenario_fluents:
                            branch_act.add_effect(scenario_fluents[script_name], True)
                    for script_name in npc_scenario_calls.get(npc_id, {}).get(
                        src_knot, set()
                    ):
                        if script_name in scenario_fluents:
                            branch_act.add_effect(scenario_fluents[script_name], True)

                    # Check get() guards for this target
                    cond_matches = [c for c in src_conds if c[0] == tgt_knot]
                    # Check has() guards for this target
                    has_matches = [c for c in src_hass if c[0] == tgt_knot]
                    target_expressions = [
                        expression
                        for target, expression in guard_expressions.get(src_knot, [])
                        if target == tgt_knot
                    ]

                    planning_expressions = [
                        to_planning_expression(expression, npc_id)
                        for expression in target_expressions
                    ]
                    if target_expressions and all(
                        expression is not None for expression in planning_expressions
                    ):
                        for expression in planning_expressions:
                            branch_act.add_precondition(expression)
                    else:
                        for cond in cond_matches:
                            _, var_path, negated = cond
                            bound_k = resolve_bound_path(var_path, npc_id)
                            if bound_k in var_fluents_true:
                                if negated:
                                    branch_act.add_precondition(
                                        var_fluents_false[bound_k]
                                    )
                                else:
                                    branch_act.add_precondition(
                                        var_fluents_true[bound_k]
                                    )
                        for has_cond in has_matches:
                            _, list_path, item_name, negated = has_cond
                            bound_list = resolve_bound_path(list_path, npc_id)
                            key = (bound_list, item_name)
                            if key in has_fluents_true:
                                if negated:
                                    branch_act.add_precondition(has_fluents_false[key])
                                else:
                                    branch_act.add_precondition(has_fluents_true[key])

                    # Apply set() mutations from target knot
                    add_set_effects(branch_act, set_muts.get(tgt_knot, []), npc_id)
                    add_completion_effects(branch_act, set_muts.get(tgt_knot, []))
                    add_move_effects(branch_act, move_muts.get(tgt_knot, []), npc_id)
                    if any(
                        move[0] == "$player" and move[2] == PASS_MOVE_DESTINATION
                        for move in move_muts.get(tgt_knot, [])
                    ):
                        add_pass_effects(branch_act, npc_id)

                    # Apply list mutations from target knot.
                    # If the branch removes an item from the player inventory, we must
                    # already possess it before taking that branch.
                    add_list_mutation_effects(
                        branch_act, list_muts.get(tgt_knot, []), npc_id
                    )

                    problem.add_action(branch_act)

            # End dialogue action to return to explore
            end_act = up.InstantaneousAction(f"end_dialogue_{npc_id}_{src_knot}")
            end_act.add_precondition(in_dialogue(npc_obj))
            end_act.add_precondition(at_knot(npc_obj, knot_objs[src_knot]))
            end_act.add_effect(in_dialogue(npc_obj), False)
            end_act.add_effect(at_knot(npc_obj, knot_objs[src_knot]), False)
            end_act.add_effect(in_explore, True)
            for room in room_objs.values():
                end_act.add_effect(pending_move(room), False)
            problem.add_action(end_act)
    for (source, destination), npc_id in movement_interceptors.items():
        knot_objs = knot_objects_by_npc.get(npc_id)
        if not knot_objs or "__root__" not in knot_objs:
            continue
        intercept_act = up.InstantaneousAction(
            f"intercept_{source}_to_{destination}_{npc_id}"
        )
        intercept_act.add_precondition(at_room(room_objs[source]))
        intercept_act.add_precondition(in_explore)
        accost_path = resolve_bound_path(f"{npc_id}.accosts", npc_id)
        if (source, destination) in movement_accost_interceptors:
            intercept_act.add_precondition(var_fluents_true[accost_path])
        intercept_act.add_effect(in_explore, False)
        intercept_act.add_effect(in_dialogue(problem.object(npc_id)), True)
        intercept_act.add_effect(
            at_knot(problem.object(npc_id), knot_objs["__root__"]), True
        )
        for room in room_objs.values():
            intercept_act.add_effect(pending_move(room), False)
        intercept_act.add_effect(pending_move(room_objs[destination]), True)
        add_set_effects(
            intercept_act,
            npc_set_mutations.get(npc_id, {}).get("__root__", []),
            npc_id,
        )
        add_completion_effects(
            intercept_act, npc_set_mutations.get(npc_id, {}).get("__root__", [])
        )
        add_list_mutation_effects(
            intercept_act,
            npc_list_mutations.get(npc_id, {}).get("__root__", []),
            npc_id,
        )
        add_move_effects(
            intercept_act,
            npc_move_mutations.get(npc_id, {}).get("__root__", []),
            npc_id,
        )
        problem.add_action(intercept_act)

    if profiler:
        profiler.add_time("Action generation", monotonic() - action_generation_started)

    # Test completion goals independently from the original game state. Fast
    # Downward translates their disjunction once, then each search targets one
    # quest flag.
    incomplete_quests = [
        quest_id for quest_id in quest_ids if not quest_set_candidates.get(quest_id)
    ]
    state_example = []
    if profiler:
        for fluent in problem.fluents:
            if not fluent.signature and problem.initial_value(fluent()).is_true():
                state_example.append(str(fluent))
        state_example.append(f"at_room({start_room})")

    def save_satisficing_plan(quest_id: str, result: Any, planner_name: str) -> None:
        if result.status.name != "SOLVED_SATISFICING" or result.plan is None:
            return
        output_started = monotonic() if profiler else None
        artefacts_dir = game_path / "artefacts"
        artefacts_dir.mkdir(parents=True, exist_ok=True)
        plan_path = artefacts_dir / f"{quest_id}.txt"
        plan_path.write_text(
            f"Quest: {quest_id}\n"
            f"Planner: {planner_name}\n"
            f"Status: {result.status.name}\n\n"
            f"{result.plan}\n",
            encoding="utf-8",
        )
        if profiler and output_started is not None:
            profiler.add_time("Plan artifact output", monotonic() - output_started)

    search_started = monotonic() if profiler else None
    if profiler:
        planner_initialization_started = monotonic()
        with up.OneshotPlanner(
            name="fast-downward",
            problem_kind=problem.kind,
            params={
                "fast_downward_search_config": "eager_greedy([ff()])",
            },
        ) as planner:
            profiler.add_time(
                "Planner initialization", monotonic() - planner_initialization_started
            )
            profiler.planner_name = planner.name
            active_quests = [
                quest_id for quest_id in quest_ids if quest_set_candidates.get(quest_id)
            ]
            if active_quests:
                try:
                    records, translation_seconds, timed_out_quest = (
                        _solve_fast_downward_quests(
                            problem,
                            quest_completed,
                            active_quests,
                            planner,
                            profiler.remaining(),
                        )
                    )
                except (OSError, RuntimeError, ValueError) as error:
                    raise RuntimeError(
                        "Could not reuse Fast Downward's translated quest task"
                    ) from error
                profiler.solver_calls += len(records)
                profiler.solver_seconds += translation_seconds + sum(
                    record["search_seconds"] for record in records.values()
                )
                profiler.add_time("Shared Fast Downward translation", translation_seconds)
                profiler.add_time(
                    "Fast Downward search",
                    sum(record["search_seconds"] for record in records.values()),
                )
                for index, quest_id in enumerate(active_quests):
                    record = records.get(quest_id)
                    if record is None:
                        incomplete_quests.append(quest_id)
                        continue
                    res = record["result"]
                    output = record["output"]
                    is_timeout = record["timeout"]
                    seconds = record["translation_seconds"] + record["search_seconds"]
                    if record.get("goal_pruned"):
                        status = "UNSOLVABLE_PROVEN"
                        expanded_nodes = None
                        profiler.expanded_node_unavailable += 1
                        incomplete_quests.append(quest_id)
                    elif is_timeout:
                        profiler.stopped = True
                        profiler.stop_reason = (
                            "Fast Downward translation or search timed out"
                        )
                        profiler.expanded_node_unavailable += 1
                        status = "TIMEOUT"
                        expanded_nodes = None
                        incomplete_quests.extend(active_quests[index:])
                    else:
                        status = res.status.name
                        expanded_nodes = _expanded_node_count(res)
                        if expanded_nodes is None:
                            profiler.expanded_node_unavailable += 1
                        else:
                            profiler.expanded_nodes += expanded_nodes
                            profiler.expanded_node_results += 1
                        save_satisficing_plan(quest_id, res, planner.name)
                        if status not in ("SOLVED_SATISFICING", "SOLVED_OPTIMALLY"):
                            incomplete_quests.append(quest_id)
                    profiler.solver_records.append(
                        {
                            "goal": f"quest:{quest_id}",
                            "seconds": seconds,
                            "status": status,
                            "expanded_nodes": expanded_nodes,
                            "fd_output": output,
                            "fd_phase_times": {
                                **(
                                    {"translator": translation_seconds}
                                    if index == 0
                                    else {}
                                ),
                                **(
                                    {"search": record["search_seconds"]}
                                    if record["search_seconds"]
                                    else {}
                                ),
                            },
                            "fd_translation_reused": index > 0,
                        }
                    )
                    if is_timeout:
                        break
    else:
        active_quests = [
            quest_id for quest_id in quest_ids if quest_set_candidates.get(quest_id)
        ]
        if up_fast_downward is not None:
            with up.OneshotPlanner(
                name="fast-downward",
                problem_kind=problem.kind,
                params={"fast_downward_search_config": "eager_greedy([ff()])"},
            ) as planner:
                records, _, timed_out_quest = _solve_fast_downward_quests(
                    problem, quest_completed, active_quests, planner
                )
                for quest_id in active_quests:
                    record = records.get(quest_id)
                    res = record["result"] if record else None
                    if (
                        res is not None
                        and res.status.name
                        in ("SOLVED_SATISFICING", "SOLVED_OPTIMALLY")
                    ):
                        save_satisficing_plan(quest_id, res, planner.name)
                    else:
                        incomplete_quests.append(quest_id)
                    if quest_id == timed_out_quest:
                        break
                if timed_out_quest:
                    incomplete_quests.extend(
                        quest_id
                        for quest_id in active_quests
                        if quest_id not in records
                    )
        else:
            with up.OneshotPlanner(
                names=_planner_names(), problem_kind=problem.kind
            ) as planner:
                for quest_id in active_quests:
                    problem.clear_goals()
                    problem.add_goal(quest_completed[quest_id])
                    res = planner.solve(problem)
                    save_satisficing_plan(quest_id, res, planner.name)
                    if res.status.name not in (
                        "SOLVED_SATISFICING",
                        "SOLVED_OPTIMALLY",
                    ):
                        incomplete_quests.append(quest_id)

    if profiler and search_started is not None:
        # Planner context entry, the shared translation, per-quest searches,
        # and plan output account for the profiled search interval. Keep any
        # small remainder visible rather than folding it into a measured phase.
        search_elapsed = monotonic() - search_started
        measured_search = sum(
            profiler.phase_seconds.get(phase, 0.0)
            for phase in (
                "Planner initialization",
                "Shared Fast Downward translation",
                "Fast Downward search",
                "Plan artifact output",
            )
        )
        profiler.add_time(
            "Planner overhead", max(0.0, search_elapsed - measured_search)
        )

    if incomplete_quests:
        print(
            f"Warning: quests not completable: {', '.join(sorted(set(incomplete_quests)))}"
        )
    if profiler:
        profiler.report(problem, state_example, verbose)

    return sorted(set(incomplete_quests))


def validate_world(game_path: Path | str) -> list[str]:
    """Alias for validate_quests for backwards compatibility with validate/rooms.py."""
    return validate_quests(game_path)


class QuestValidator:
    """Validator class for quest and reachability validation."""

    def __init__(self, game_path: Path | str):
        self.game_path = Path(game_path)

    def validate(self) -> list[str]:
        return validate_quests(self.game_path)

    def validate_room_reachability(self) -> list[str]:
        return validate_quests(self.game_path)


if __name__ == "__main__":
    game_dir = argv[1]
    validate_quests(Path(f"{game_dir}"), profile="--profile" in argv[2:], verbose="--verbose" in argv[2:])
