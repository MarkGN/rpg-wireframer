from __future__ import annotations

from pathlib import Path
from sys import argv
from typing import Any

import unified_planning as up
import yaml
from unified_planning.engines import PlanGenerationResultStatus
from unified_planning.shortcuts import (
    BoolType,
    Fluent,
    InstantaneousAction,
    OneshotPlanner,
    Problem,
)

from runners import world

# Silence engine credits output
up.shortcuts.get_environment().credits_stream = None


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def validate_quests(game_path: Path | str) -> list[str]:
    """Validate room reachability using a STRIPS planning model via Unified-Planning & Pyperplan."""
    game_path = Path(game_path)
    w = world.World(game_path)

    rooms = w.world_state["rooms"]
    player_handle = w.player_handle
    start_room = w.current_room

    # Build STRIPS planning problem using Unified-Planning
    base_problem = Problem("room_reachability")

    # Create fluents at_<player, room> for each room
    fluents: dict[str, Any] = {}
    for room_id in rooms:
        fluent_name = f"at_{player_handle},{room_id}"
        fluent = Fluent(fluent_name, BoolType())
        base_problem.add_fluent(fluent, default_initial_value=False)
        fluents[room_id] = fluent

    # Initial state: player is in start_room
    base_problem.set_initial_value(fluents[start_room], True)

    # Actions: for every exit from A to B, action requires at_player,A and establishes at_player,B removing at_player,A
    for room_id, room_data in rooms.items():
        exits = room_data.get("exits", [])
        next_rooms = exits.values() if isinstance(exits, dict) else exits
        for next_room in next_rooms:
            if next_room in rooms:
                action_name = f"move_{player_handle}_{room_id}_to_{next_room}"
                action = InstantaneousAction(action_name)
                action.add_precondition(fluents[room_id])
                action.add_effect(fluents[room_id], False)
                action.add_effect(fluents[next_room], True)
                base_problem.add_action(action)

    # Check reachability for each room
    unreachable: list[str] = []
    with OneshotPlanner(name="pyperplan") as planner:
        for room_id in sorted(rooms.keys()):
            if room_id == start_room:
                continue
            prob = base_problem.clone()
            prob.add_goal(prob.fluent(f"at_{player_handle},{room_id}"))
            res = planner.solve(prob)
            if res.status not in (
                PlanGenerationResultStatus.SOLVED_SATISFICING,
                PlanGenerationResultStatus.SOLVED_OPTIMALLY,
            ):
                unreachable.append(room_id)

    unreachable = sorted(unreachable)
    if unreachable:
        print(f"Warning: unreachable rooms: {', '.join(unreachable)}")

    return unreachable


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
