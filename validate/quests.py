from __future__ import annotations

from pathlib import Path
from sys import argv
from typing import Any

import unified_planning.shortcuts as up

up.get_environment().credits_stream = None
import yaml

from runners import world
from validate.ink_analyser import analyze_ink_file, find_ink_path


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_quests(game_path: Path | str) -> list[str]:
    """Validate quest reachability using goal-directed STRIPS planning for quests with a goal_room field."""
    game_path = Path(game_path)
    w = world.World(game_path)
    rooms = w.world_state["rooms"]
    game_objects = w.world_state["game_objects"]
    player_handle = w.world_state["player_handle"]
    start_room = w.current_room
    dialogue_dir = game_path / "dialogue"

    # Map NPC dialogues
    npc_dialogue_graphs: dict[str, dict[str, set[str]]] = {}
    for obj_id, obj_data in game_objects.items():
        if obj_id == player_handle:
            continue
        ink_ref = obj_data.get("ink", obj_data.get("dialogue", f"{obj_id}.ink"))
        if isinstance(ink_ref, str):
            ink_ref = ink_ref.removesuffix(".ink")
            ink_file = find_ink_path(f"{ink_ref}.ink", dialogue_dir)
            if ink_file and ink_file.exists():
                try:
                    graph, _ = analyze_ink_file(f"{ink_ref}.ink", dialogue_dir, game_path)
                    npc_dialogue_graphs[obj_id] = graph
                except (OSError, ValueError, TypeError):
                    pass

    # Read quest files in world/quests/
    quests_dir = game_path / "world" / "quests"
    goal_room_quests: dict[str, str] = {}
    if quests_dir.exists() and quests_dir.is_dir():
        for q_file in sorted(quests_dir.glob("*.yaml")):
            q_data = load_yaml(q_file)
            if isinstance(q_data, dict) and "goal_room" in q_data:
                goal_room_quests[q_file.stem] = str(q_data["goal_room"])

    if not goal_room_quests:
        return []

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
    for npc_id, graph in npc_dialogue_graphs.items():
        npc_obj = up.Object(npc_id, NPC)
        problem.add_object(npc_obj)

        knot_objs: dict[str, Any] = {}
        for knot_name in graph:
            k_obj = up.Object(f"{npc_id}_{knot_name}", Knot)
            problem.add_object(k_obj)
            knot_objs[knot_name] = k_obj

        npc_room = game_objects.get(npc_id, {}).get("location")
        if npc_room in room_objs:
            talk_act = up.InstantaneousAction(f"talk_{npc_id}")
            talk_act.add_precondition(at_room(room_objs[npc_room]))
            talk_act.add_precondition(in_explore)
            talk_act.add_effect(in_explore, False)
            talk_act.add_effect(in_dialogue(npc_obj), True)
            talk_act.add_effect(at_knot(npc_obj, knot_objs["__root__"]), True)
            problem.add_action(talk_act)

        for src_knot, targets in graph.items():
            if src_knot not in knot_objs:
                continue
            for tgt_knot in targets:
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

    # Solve for each quest goal_room using goal-directed planner
    uncompletable_quests: list[str] = []
    with up.OneshotPlanner(problem_kind=problem.kind) as planner:
        for q_name, g_room in goal_room_quests.items():
            if g_room not in room_objs:
                uncompletable_quests.append(q_name)
                continue

            problem.clear_goals()
            problem.add_goal(at_room(room_objs[g_room]))

            res = planner.solve(problem)
            if res.status.name not in ("SOLVED_SATISFICING", "SOLVED_OPTIMALLY"):
                uncompletable_quests.append(q_name)

    if uncompletable_quests:
        raise ValueError(f"Quests not completable: {', '.join(sorted(uncompletable_quests))}")

    return []


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
