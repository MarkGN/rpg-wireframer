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

# Silence engine credits output
up.shortcuts.get_environment().credits_stream = None


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def validate_quests(game_path: Path | str) -> list[str]:
    """Validate room reachability using a STRIPS planning model via Unified-Planning & Pyperplan."""
    game_path = Path(game_path)
    world_dir = game_path / "world"
    rooms_dir = world_dir / "rooms"
    game_objects_dir = world_dir / "game_objects"
    game_file = world_dir / "game.yaml"

    rooms: dict[str, dict[str, Any]] = {}
    for path in sorted(rooms_dir.rglob("*.yaml")):
        room_id = path.stem
        rooms[room_id] = load_yaml(path)

    if not rooms:
        raise ValueError(f"No rooms found in {rooms_dir}")

    game_data = load_yaml(game_file)
    player_handle = game_data.get("player")
    if not player_handle:
        raise ValueError(f"No player defined in {game_file}")

    player_path = None
    for path in sorted(game_objects_dir.rglob("*.yaml")):
        if path.stem == player_handle:
            player_path = path
            break
    if player_path is None:
        raise ValueError(
            f"Player data not found for '{player_handle}' under {game_objects_dir}"
        )

    player_data = load_yaml(player_path)
    start_room = player_data.get("location")

    object_handles = {path.stem for path in sorted(game_objects_dir.rglob("*.yaml"))}
    for room_data in rooms.values():
        for obj in room_data.get("objects", []) or []:
            if isinstance(obj, str):
                object_handles.add(obj)
            elif isinstance(obj, dict) and len(obj) == 1 and isinstance(next(iter(obj.values())), dict):
                obj_handle = next(iter(obj.keys()))
                if isinstance(obj_handle, str):
                    object_handles.add(obj_handle)

    if isinstance(start_room, str) and start_room in rooms:
        pass
    else:
        player_rooms = [
            room_id
            for room_id, room_data in rooms.items()
            if player_handle
            in [
                obj if isinstance(obj, str) else next(iter(obj.keys()))
                for obj in room_data.get("objects", []) or []
                if isinstance(obj, str) or (isinstance(obj, dict) and len(obj) == 1)
            ]
        ]
        if len(player_rooms) == 1:
            start_room = player_rooms[0]
        else:
            raise ValueError(
                f"Player location '{start_room}' is not a valid room in {rooms_dir}"
            )

    for path in sorted(game_objects_dir.rglob("*.yaml")):
        object_data = load_yaml(path)
        location = object_data.get("location")
        if location is None:
            continue
        if isinstance(location, str):
            if location not in rooms:
                raise ValueError(
                    f"Object {path.stem} points to unknown room '{location}'"
                )
        elif isinstance(location, list):
            invalid_rooms = [
                room
                for room in location
                if not isinstance(room, str) or room not in rooms
            ]
            if invalid_rooms:
                raise ValueError(
                    f"Object {path.stem} points to unknown rooms: {invalid_rooms}"
                )
        else:
            raise TypeError(
                f"Object {path.stem} has invalid location value {location!r}"
            )

    for room_id, room_data in rooms.items():
        exits = room_data.get("exits", [])
        if isinstance(exits, dict):
            invalid_exits = [
                target
                for target in exits.values()
                if not isinstance(target, str) or target not in rooms
            ]
            if invalid_exits:
                raise ValueError(
                    f"Room {room_id} links to unknown exits: {invalid_exits}"
                )
        elif isinstance(exits, list):
            invalid_exits = [
                target
                for target in exits
                if not isinstance(target, str) or target not in rooms
            ]
            if invalid_exits:
                raise ValueError(
                    f"Room {room_id} links to unknown exits: {invalid_exits}"
                )
        else:
            raise TypeError(f"Room {room_id} has invalid exits value {exits!r}")

        objects = room_data.get("objects")
        if objects is None:
            continue
        if not isinstance(objects, list):
            raise TypeError(f"Room {room_id} has invalid objects value {objects!r}")
        for obj in objects:
            if isinstance(obj, str):
                if obj not in object_handles:
                    raise ValueError(
                        f"Room {room_id} references unknown object '{obj}'"
                    )
            elif isinstance(obj, dict):
                if len(obj) == 1 and isinstance(next(iter(obj.values())), dict):
                    obj_handle, obj_data = next(iter(obj.items()))
                else:
                    obj_handle = None
                    obj_data = obj
                if obj_handle is not None and not isinstance(obj_handle, str):
                    raise TypeError(
                        f"Room {room_id} has invalid inline object handle {obj_handle!r}"
                    )
                if not isinstance(obj_data, dict):
                    raise TypeError(
                        f"Room {room_id} inline object must be a mapping, got {obj!r}"
                    )
                base = obj_data.get("inherits")
                template = obj_data.get("template")
                if base is not None and (
                    not isinstance(base, str) or base not in object_handles
                ):
                    raise ValueError(
                        f"Room {room_id} inline object references unknown base '{base}'"
                    )
                if template is not None and (
                    not isinstance(template, str) or template not in object_handles
                ):
                    raise ValueError(
                        f"Room {room_id} inline object references unknown template '{template}'"
                    )
                if base is not None and template is not None:
                    raise ValueError(
                        f"Room {room_id} inline object cannot define both 'inherits' and 'template'"
                    )
            else:
                raise TypeError(f"Room {room_id} has invalid object entry {obj!r}")

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
