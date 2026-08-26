from __future__ import annotations

from pathlib import Path
from sys import argv
from typing import Any

import unified_planning.shortcuts as up

up.get_environment().credits_stream = None
import yaml

from runners import world
from runners.binder import Binder
from validate.ink_analyser import analyze_ink_file, find_ink_path


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _evaluate_get_condition(var_path: str, npc_id: str, w: world.World) -> bool:
    try:
        npc_room = ""
        try:
            npc_room = w.find_npc(npc_id)
        except SystemExit:
            pass
        bound_path = Binder(
            {
                "player": w.player_handle,
                "self": npc_id,
                "current_room": w.current_room,
                "npc_room": npc_room,
            }
        ).apply(var_path)
        val = w.get_state(bound_path)
        return bool(val)
    except (KeyError, IndexError, TypeError):
        return False


def validate_quests(game_path: Path | str) -> list[str]:
    """Validate dialogue knot reachability with read-only persistent state (evaluating get() guards)."""
    game_path = Path(game_path)
    w = world.World(game_path)
    rooms = w.world_state["rooms"]
    game_objects = w.world_state["game_objects"]
    player_handle = w.world_state["player_handle"]
    start_room = w.current_room
    dialogue_dir = game_path / "dialogue"

    # Map NPC dialogues
    npc_dialogue_graphs: dict[str, dict[str, set[str]]] = {}
    npc_get_conditions: dict[str, dict[str, list[tuple[str, str, bool]]]] = {}

    for obj_id, obj_data in game_objects.items():
        if obj_id == player_handle:
            continue
        ink_ref = obj_data.get("ink", obj_data.get("dialogue", f"{obj_id}.ink"))
        if isinstance(ink_ref, str):
            ink_ref = ink_ref.removesuffix(".ink")
            ink_file = find_ink_path(f"{ink_ref}.ink", dialogue_dir)
            if ink_file and ink_file.exists():
                try:
                    graph, _, get_conds = analyze_ink_file(f"{ink_ref}.ink", dialogue_dir, game_path)
                    npc_dialogue_graphs[obj_id] = graph
                    npc_get_conditions[obj_id] = get_conds
                except (OSError, ValueError, TypeError):
                    pass

    # Construct STRIPS Planning Problem using unified-planning
    problem = up.Problem("quest_reachability")

    Location = up.UserType("Location")
    Knot = up.UserType("Knot")
    NPC = up.UserType("NPC")

    at_room = up.Fluent("at_room", l=Location)
    at_knot = up.Fluent("at_knot", npc=NPC, k=Knot)
    in_explore = up.Fluent("in_explore")
    in_dialogue = up.Fluent("in_dialogue", npc=NPC)

    problem.add_fluent(at_room, default_initial_value=False)
    problem.add_fluent(at_knot, default_initial_value=False)
    problem.add_fluent(in_explore, default_initial_value=True)
    problem.add_fluent(in_dialogue, default_initial_value=False)

    # Add room objects
    room_objs: dict[str, Any] = {}
    for r_name in rooms:
        r_obj = up.Object(r_name, Location)
        problem.add_object(r_obj)
        room_objs[r_name] = r_obj

    # Add initial location
    if start_room in room_objs:
        problem.set_initial_value(at_room(room_objs[start_room]), True)

    # Add room transitions (move actions)
    for r_name, r_data in rooms.items():
        if r_name not in room_objs:
            continue
        exits = r_data.get("exits", [])
        next_rooms = exits.values() if isinstance(exits, dict) else exits
        for nxt in next_rooms:
            if nxt in room_objs:
                move_act = up.InstantaneousAction(f"move_{r_name}_to_{nxt}")
                move_act.add_precondition(at_room(room_objs[r_name]))
                move_act.add_precondition(in_explore)
                move_act.add_effect(at_room(room_objs[r_name]), False)
                move_act.add_effect(at_room(room_objs[nxt]), True)
                problem.add_action(move_act)

    # Add NPC and Dialogue objects & actions
    all_npc_knots: dict[str, list[str]] = {}
    for npc_id, graph in npc_dialogue_graphs.items():
        npc_obj = up.Object(npc_id, NPC)
        problem.add_object(npc_obj)

        knot_objs: dict[str, Any] = {}
        all_npc_knots[npc_id] = [k for k in graph if k != "__root__"]
        for knot_name in graph:
            k_obj = up.Object(f"{npc_id}_{knot_name}", Knot)
            problem.add_object(k_obj)
            knot_objs[knot_name] = k_obj

        npc_room = ""
        try:
            npc_room = w.find_npc(npc_id)
        except SystemExit:
            pass
        if not npc_room:
            npc_room = game_objects.get(npc_id, {}).get("location")

        if npc_room in room_objs:
            talk_act = up.InstantaneousAction(f"talk_{npc_id}")
            talk_act.add_precondition(at_room(room_objs[npc_room]))
            talk_act.add_precondition(in_explore)
            talk_act.add_effect(in_explore, False)
            talk_act.add_effect(in_dialogue(npc_obj), True)
            talk_act.add_effect(at_knot(npc_obj, knot_objs["__root__"]), True)
            problem.add_action(talk_act)

        get_conds = npc_get_conditions.get(npc_id, {})
        for src_knot, targets in graph.items():
            if src_knot not in knot_objs:
                continue
            src_conds = get_conds.get(src_knot, [])
            for tgt_knot in targets:
                # Check if tgt_knot is governed by a get() guard
                cond_matches = [c for c in src_conds if c[0] == tgt_knot]
                if cond_matches:
                    _, var_path, negated = cond_matches[0]
                    val = _evaluate_get_condition(var_path, npc_id, w)
                    condition_satisfied = (not val) if negated else val
                    if not condition_satisfied:
                        continue  # Prune invalid branch transition

                if tgt_knot in ("done", "END"):
                    end_act = up.InstantaneousAction(f"end_dialogue_{npc_id}_{src_knot}")
                    end_act.add_precondition(in_dialogue(npc_obj))
                    end_act.add_precondition(at_knot(npc_obj, knot_objs[src_knot]))
                    end_act.add_effect(in_dialogue(npc_obj), False)
                    end_act.add_effect(at_knot(npc_obj, knot_objs[src_knot]), False)
                    end_act.add_effect(in_explore, True)
                    problem.add_action(end_act)
                elif tgt_knot in knot_objs:
                    branch_act = up.InstantaneousAction(f"branch_{npc_id}_{src_knot}_to_{tgt_knot}")
                    branch_act.add_precondition(in_dialogue(npc_obj))
                    branch_act.add_precondition(at_knot(npc_obj, knot_objs[src_knot]))
                    branch_act.add_effect(at_knot(npc_obj, knot_objs[src_knot]), False)
                    branch_act.add_effect(at_knot(npc_obj, knot_objs[tgt_knot]), True)
                    problem.add_action(branch_act)

    # Test reachability of every knot for every reachable NPC dialogue
    unreachable_knots: list[str] = []
    with up.OneshotPlanner(problem_kind=problem.kind) as planner:
        for npc_id, knot_list in all_npc_knots.items():
            npc_obj = problem.object(npc_id)
            for knot_name in knot_list:
                k_obj = problem.object(f"{npc_id}_{knot_name}")
                problem.clear_goals()
                problem.add_goal(at_knot(npc_obj, k_obj))
                res = planner.solve(problem)
                if res.status.name not in ("SOLVED_SATISFICING", "SOLVED_OPTIMALLY"):
                    unreachable_knots.append(f"{npc_id}:{knot_name}")

    if unreachable_knots:
        print(f"Warning: unreachable dialogue knots: {', '.join(sorted(unreachable_knots))}")

    return unreachable_knots


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
    validate_quests(Path(f"{game_dir}"))
