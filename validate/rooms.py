from __future__ import annotations

from pathlib import Path
from sys import argv
from typing import Any

import yaml

from runners import world


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def validate_world(game_path: Path | str) -> None:
    """Validate room and object references for a game directory."""
    game_path = Path(game_path)
    w = world.World(game_path)

    rooms = w.world_state["rooms"]
    start_room = w.current_room

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
