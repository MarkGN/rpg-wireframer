from __future__ import annotations

import signal
from contextlib import contextmanager
from pathlib import Path
from sys import argv
from time import monotonic
from typing import Any

import unified_planning.shortcuts as up

up.get_environment().credits_stream = None
try:
    import up_fast_downward
except ImportError:
    up_fast_downward = None
import yaml

from runners import world
from runners.binder import Binder
from validate.ink_analyser import (
    PASS_MOVE_DESTINATION,
    _collect_reachable_knots,
    analyze_ink_file,
    find_ink_path,
)


class _Profile:
    def __init__(self, limit_seconds: float = 60.0):
        self.started = monotonic()
        self.deadline = self.started + limit_seconds
        self.limit_seconds = limit_seconds
        self.action_seconds = {"Explore Context": 0.0, "Dialogue": 0.0}
        self.solver_calls = 0
        self.solver_seconds = 0.0
        self.stopped = False
        self.stop_reason = ""
        self.planner_name = ""
        self.solver_records: list[dict[str, Any]] = []

    def expired(self) -> bool:
        if monotonic() >= self.deadline:
            self.stopped = True
            self.stop_reason = "five-minute profiling limit reached"
            return True
        return False

    def remaining(self) -> float:
        return max(0.0, self.deadline - monotonic())

    @contextmanager
    def time_actions(self, context: str):
        started = monotonic()
        try:
            yield
        finally:
            self.action_seconds[context] += monotonic() - started

    def report(self, problem: Any | None = None, state_example: list[str] | None = None):
        elapsed = monotonic() - self.started
        total_action_seconds = sum(self.action_seconds.values())
        print("\nQuest validator profile")
        print(f"Elapsed: {elapsed:.2f}s")
        if self.stopped:
            print(f"Stopped: {self.stop_reason}")
        print(f"Solver calls: {self.solver_calls}")
        if self.planner_name:
            print(f"Planner: {self.planner_name}")
        print(f"Solver time: {self.solver_seconds:.2f}s")
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
                )
        for context, seconds in self.action_seconds.items():
            fraction = seconds / total_action_seconds if total_action_seconds else 0.0
            print(f"{context} action expansion: {seconds:.4f}s ({fraction:.1%})")
        if problem is not None:
            fluents = list(problem.fluents)
            actions = list(problem.actions)
            objects = list(problem.all_objects)
            print(
                "State/model size: "
                f"{len(fluents)} fluents, {len(actions)} actions, {len(objects)} objects"
            )
            boolean_fluents = [
                fluent for fluent in fluents if not fluent.signature
            ]
            state_count = (
                f"{2 ** len(boolean_fluents):,}"
                if len(boolean_fluents) < 1000
                else "too large to materialize"
            )
            print(
                "Estimated boolean state space: "
                f"2^{len(boolean_fluents)} ({state_count} states)"
            )
            print("Example actions:")
            for action in actions[:10]:
                print(f"  {action.name}")
        if state_example:
            print("Example initial state:")
            for fact in state_example[:30]:
                print(f"  {fact}")


@contextmanager
def _hard_timeout(seconds: float):
    """Interrupt a profiled in-process planner on Unix when it exceeds its budget."""
    if seconds <= 0:
        raise TimeoutError

    def interrupt(_signum: int, _frame: Any) -> None:
        raise TimeoutError("planner solve timed out")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, interrupt)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _planner_names() -> list[str] | None:
    if up_fast_downward is not None:
        return ["fast-downward"]
    return None


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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


def validate_quests(
    game_path: Path | str, *, profile: bool = False
) -> list[str]:
    """Validate that every declared quest can reach a truthy completion mutation."""
    game_path = Path(game_path)
    w = world.World(game_path)
    rooms = w.world_state["rooms"]
    objects = w.world_state["objects"]
    player_handle = w.player_handle
    start_room = w.current_room
    dialogue_dir = game_path / "dialogue"
    quest_ids = sorted(w.world_state.get("quests", {}))
    quest_targets = {
        quest_id: f"quests.{quest_id}.completed" for quest_id in quest_ids
    }
    profiler = _Profile() if profile else None

    def resolve_bound_path(var_path: str, npc_id: str) -> str:
        key = (var_path, npc_id)
        if key not in bound_cache:
            bound_cache[key] = _bind_var_path(var_path, npc_id, w)
        return bound_cache[key]

    bound_cache: dict[tuple[str, str], str] = {}

    # Map NPC dialogues
    npc_dialogue_graphs: dict[str, dict[str, set[str]]] = {}
    npc_get_conditions: dict[str, dict[str, list[tuple[str, str, bool]]]] = {}
    npc_set_mutations: dict[str, dict[str, list[tuple[str, Any]]]] = {}
    npc_has_conditions: dict[str, dict[str, list[tuple[str, str, str, bool]]]] = {}
    npc_list_mutations: dict[str, dict[str, list[tuple[str, str, bool]]]] = {}
    npc_move_mutations: dict[str, dict[str, list[tuple[str, str, str]]]] = {}

    for obj_id, obj_data in objects.items():
        if obj_id == player_handle:
            continue
        ink_ref = obj_data.get("ink", obj_data.get("dialogue", f"{obj_id}.ink"))
        if isinstance(ink_ref, str):
            ink_ref = ink_ref.removesuffix(".ink")
            ink_file = find_ink_path(f"{ink_ref}.ink", dialogue_dir)
            if ink_file and ink_file.exists():
                try:
                    (
                        graph,
                        _,
                        get_conds,
                        set_muts,
                        has_conds,
                        list_muts,
                        move_muts,
                    ) = analyze_ink_file(f"{ink_ref}.ink", dialogue_dir, game_path)
                    npc_dialogue_graphs[obj_id] = graph
                    npc_get_conditions[obj_id] = get_conds
                    npc_set_mutations[obj_id] = set_muts
                    npc_has_conditions[obj_id] = has_conds
                    npc_list_mutations[obj_id] = list_muts
                    npc_move_mutations[obj_id] = move_muts
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
        dyn = any(
            bool(cond_list) for knot_name, cond_list in cond_map.items() if knot_name in reachable_knots
        ) or any(
            bool(mut_list) for knot_name, mut_list in mut_map.items() if knot_name in reachable_knots
        ) or any(
            bool(has_list) for knot_name, has_list in has_map.items() if knot_name in reachable_knots
        ) or any(
            bool(list_list) for knot_name, list_list in list_map.items() if knot_name in reachable_knots
        ) or any(
            bool(move_list) for knot_name, move_list in move_map.items() if knot_name in reachable_knots
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

    def guard_matches(
        guard: str, target: str, destination: str | None
    ) -> bool:
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
                exit_data.get("blocker")
                if isinstance(exit_data, dict)
                else None
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

    # Construct STRIPS Planning Problem using unified-planning.
    # We now prune to only state variables that can actually affect reachability
    # in the reachable dialogue subgraph, so the planner sees only relevant state.
    relevant_var_paths: set[str] = set()
    relevant_list_paths: set[tuple[str, str]] = set()
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
                relevant_list_paths.add((resolve_bound_path(list_path, npc_id), item_name))
        for knot_name, list_list in npc_list_mutations.get(npc_id, {}).items():
            if knot_name not in relevant:
                continue
            for list_path, item_name, _ in list_list:
                relevant_list_paths.add((resolve_bound_path(list_path, npc_id), item_name))
    relevant_var_paths.update(movement_accost_paths)

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
                action.add_effect(
                    at_room(room), False, condition=condition
                )
            action.add_effect(at_room(room_objs[destination]), True, condition=condition)
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

    # Add room objects
    room_objs: dict[str, Any] = {}
    for r_name in rooms:
        r_obj = up.Object(r_name, Location)
        problem.add_object(r_obj)
        room_objs[r_name] = r_obj

    # Add initial location
    if start_room in room_objs:
        problem.set_initial_value(at_room(room_objs[start_room]), True)

    # Add room item pickups (take actions)
    if profiler:
        action_timer = profiler.time_actions("Explore Context")
        action_timer.__enter__()
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
    if profiler:
        action_timer.__exit__(None, None, None)

    # Add room transitions (move actions)
    if profiler:
        action_timer = profiler.time_actions("Explore Context")
        action_timer.__enter__()
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
    if profiler:
        action_timer.__exit__(None, None, None)

    # Add NPC and Dialogue objects & actions
    all_npc_knots: dict[str, list[str]] = {}
    knot_objects_by_npc: dict[str, dict[str, Any]] = {}
    if profiler:
        action_timer = profiler.time_actions("Explore Context")
        action_timer.__enter__()
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
            talk_act.add_precondition(at_room(room_objs[npc_room]))
            talk_act.add_precondition(in_explore)
            talk_act.add_effect(in_explore, False)
            talk_act.add_effect(in_dialogue(npc_obj), True)
            talk_act.add_effect(at_knot(npc_obj, knot_objs["__root__"]), True)
            # Apply set mutations from __root__
            for set_k, set_v in npc_set_mutations.get(npc_id, {}).get("__root__", []):
                bound_k = resolve_bound_path(set_k, npc_id)
                if bound_k in var_fluents_true:
                    val_bool = bool(set_v)
                    talk_act.add_effect(var_fluents_true[bound_k], val_bool)
                    talk_act.add_effect(var_fluents_false[bound_k], not val_bool)
            add_completion_effects(
                talk_act, npc_set_mutations.get(npc_id, {}).get("__root__", [])
            )
            # Apply list mutations from __root__
            for list_path, item_name, is_add in npc_list_mutations.get(npc_id, {}).get("__root__", []):
                bound_list = resolve_bound_path(list_path, npc_id)
                key = (bound_list, item_name)
                if key in has_fluents_true:
                    talk_act.add_effect(has_fluents_true[key], is_add)
                    talk_act.add_effect(has_fluents_false[key], not is_add)
            add_move_effects(
                talk_act, npc_move_mutations.get(npc_id, {}).get("__root__", []), npc_id
            )
            problem.add_action(talk_act)

    if profiler:
        action_timer.__exit__(None, None, None)

    if profiler:
        action_timer = profiler.time_actions("Dialogue")
        action_timer.__enter__()
    for npc_id, graph in stateful_npc_dialogues.items():
        npc_obj = problem.object(npc_id)
        knot_objs = {
            knot_name: problem.object(f"{npc_id}_{knot_name}")
            for knot_name in graph
        }
        get_conds = npc_get_conditions.get(npc_id, {})
        set_muts = npc_set_mutations.get(npc_id, {})
        has_conds = npc_has_conditions.get(npc_id, {})
        list_muts = npc_list_mutations.get(npc_id, {})
        move_muts = npc_move_mutations.get(npc_id, {})
        for src_knot, targets in graph.items():
            if src_knot not in knot_objs:
                continue
            src_conds = get_conds.get(src_knot, [])
            src_hass = has_conds.get(src_knot, [])
            for tgt_knot in targets:
                if tgt_knot in knot_objs:
                    branch_act = up.InstantaneousAction(f"branch_{npc_id}_{src_knot}_to_{tgt_knot}")
                    branch_act.add_precondition(in_dialogue(npc_obj))
                    branch_act.add_precondition(at_knot(npc_obj, knot_objs[src_knot]))
                    branch_act.add_effect(at_knot(npc_obj, knot_objs[src_knot]), False)
                    branch_act.add_effect(at_knot(npc_obj, knot_objs[tgt_knot]), True)

                    # Check get() guards for this target
                    cond_matches = [c for c in src_conds if c[0] == tgt_knot]
                    for cond in cond_matches:
                        _, var_path, negated = cond
                        bound_k = resolve_bound_path(var_path, npc_id)
                        if bound_k in var_fluents_true:
                            if negated:
                                branch_act.add_precondition(var_fluents_false[bound_k])
                            else:
                                branch_act.add_precondition(var_fluents_true[bound_k])

                    # Check has() guards for this target
                    has_matches = [c for c in src_hass if c[0] == tgt_knot]
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
                    for set_k, set_v in set_muts.get(tgt_knot, []):
                        bound_k = resolve_bound_path(set_k, npc_id)
                        if bound_k in var_fluents_true:
                            val_bool = bool(set_v)
                            branch_act.add_effect(var_fluents_true[bound_k], val_bool)
                            branch_act.add_effect(var_fluents_false[bound_k], not val_bool)
                    add_completion_effects(branch_act, set_muts.get(tgt_knot, []))
                    add_move_effects(branch_act, move_muts.get(tgt_knot, []), npc_id)
                    if any(
                        move[0] == "$player" and move[2] == PASS_MOVE_DESTINATION
                        for move in move_muts.get(tgt_knot, [])
                    ):
                        add_pass_effects(branch_act, npc_id)

                    # Apply list mutations from target knot
                    for list_path, item_name, is_add in list_muts.get(tgt_knot, []):
                        bound_list = resolve_bound_path(list_path, npc_id)
                        key = (bound_list, item_name)
                        if key in has_fluents_true:
                            branch_act.add_effect(has_fluents_true[key], is_add)
                            branch_act.add_effect(has_fluents_false[key], not is_add)

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
    if profiler:
        action_timer.__exit__(None, None, None)

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
        for set_k, set_v in npc_set_mutations.get(npc_id, {}).get("__root__", []):
            bound_k = resolve_bound_path(set_k, npc_id)
            if bound_k in var_fluents_true:
                val_bool = bool(set_v)
                intercept_act.add_effect(var_fluents_true[bound_k], val_bool)
                intercept_act.add_effect(var_fluents_false[bound_k], not val_bool)
        add_completion_effects(
            intercept_act, npc_set_mutations.get(npc_id, {}).get("__root__", [])
        )
        for list_path, item_name, is_add in npc_list_mutations.get(npc_id, {}).get(
            "__root__", []
        ):
            bound_list = resolve_bound_path(list_path, npc_id)
            key = (bound_list, item_name)
            if key in has_fluents_true:
                intercept_act.add_effect(has_fluents_true[key], is_add)
                intercept_act.add_effect(has_fluents_false[key], not is_add)
        add_move_effects(
            intercept_act, npc_move_mutations.get(npc_id, {}).get("__root__", []), npc_id
        )
        problem.add_action(intercept_act)

    # Test only the completion goals declared by quest definitions. This avoids
    # restarting the planner for every dialogue knot.
    incomplete_quests = [
        quest_id
        for quest_id in quest_ids
        if not quest_set_candidates.get(quest_id)
    ]
    state_example = []
    if profiler:
        for fluent in problem.fluents:
            if not fluent.signature and problem.initial_value(fluent()).is_true():
                state_example.append(str(fluent))
        state_example.append(f"at_room({start_room})")

    def save_satisficing_plan(
        quest_id: str, result: Any, planner_name: str
    ) -> None:
        if result.status.name != "SOLVED_SATISFICING" or result.plan is None:
            return
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

    if profiler:
        checked_quests: set[str] = set()
        with up.OneshotPlanner(
            names=_planner_names(), problem_kind=problem.kind
        ) as planner:
            profiler.planner_name = planner.name
            for quest_id in quest_ids:
                if not quest_set_candidates.get(quest_id):
                    continue
                checked_quests.add(quest_id)
                problem.clear_goals()
                problem.add_goal(quest_completed[quest_id])
                if profiler.expired():
                    break
                profiler.solver_calls += 1
                solve_started = monotonic()
                try:
                    with _hard_timeout(profiler.remaining()):
                        res = planner.solve(problem)
                except TimeoutError:
                    profiler.stopped = True
                    profiler.stop_reason = "planner solve timed out"
                    solve_seconds = monotonic() - solve_started
                    profiler.solver_seconds += solve_seconds
                    profiler.solver_records.append(
                        {
                            "goal": f"quest:{quest_id}",
                            "seconds": solve_seconds,
                            "status": "TIMEOUT",
                        }
                    )
                    break
                solve_seconds = monotonic() - solve_started
                profiler.solver_seconds += solve_seconds
                profiler.solver_records.append(
                    {
                        "goal": f"quest:{quest_id}",
                        "seconds": solve_seconds,
                        "status": res.status.name,
                    }
                )
                save_satisficing_plan(quest_id, res, planner.name)
                if res.status.name not in ("SOLVED_SATISFICING", "SOLVED_OPTIMALLY"):
                    incomplete_quests.append(quest_id)
                if profiler.expired():
                    break
            if profiler.stopped:
                incomplete_quests.extend(
                    quest_id
                    for quest_id in quest_ids
                    if quest_id not in checked_quests
                    and quest_set_candidates.get(quest_id)
                )
        # The timeout path above intentionally stops checking later quests.
    else:
        with up.OneshotPlanner(
            names=_planner_names(), problem_kind=problem.kind
        ) as planner:
            for quest_id in quest_ids:
                if not quest_set_candidates.get(quest_id):
                    continue
                problem.clear_goals()
                problem.add_goal(quest_completed[quest_id])
                res = planner.solve(problem)
                save_satisficing_plan(quest_id, res, planner.name)
                if res.status.name not in ("SOLVED_SATISFICING", "SOLVED_OPTIMALLY"):
                    incomplete_quests.append(quest_id)

    if incomplete_quests:
        print(f"Warning: quests not completable: {', '.join(sorted(set(incomplete_quests)))}")
    if profiler:
        profiler.report(problem, state_example)

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
    validate_quests(Path(f"{game_dir}"), profile="--profile" in argv[2:])
