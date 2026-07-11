from __future__ import annotations

from pathlib import Path
from sys import argv
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def validate_world(game_path: Path | str) -> None:
    """Validate room and object references for a game directory."""
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
    if not isinstance(start_room, str) or start_room not in rooms:
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
            raise ValueError(
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
            raise ValueError(f"Room {room_id} has invalid exits value {exits!r}")

    visited: set[str] = set()
    stack = [start_room]
    while stack:
        current_room = stack.pop()
        if current_room in visited:
            continue
        visited.add(current_room)
        exits = rooms[current_room].get("exits", [])
        if isinstance(exits, dict):
            next_rooms = exits.values()
        else:
            next_rooms = exits
        for next_room in next_rooms:
            if next_room in rooms and next_room not in visited:
                stack.append(next_room)

    unreachable = sorted(set(rooms) - visited)
    if unreachable:
        print(f"Warning: unreachable rooms: {', '.join(unreachable)}")


if __name__ == "__main__":
    game_dir = argv[1]
    validate_world(Path(f"{game_dir}"))
