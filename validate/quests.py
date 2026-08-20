from __future__ import annotations

from collections import deque
from pathlib import Path
from sys import argv
from typing import Any

import yaml

from runners import world
from validate.ink_analyser import analyze_ink_file, find_ink_path


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}



def validate_quests(game_path: Path | str) -> list[str]:
    """Validate room reachability and dialogue knot reachability using graph search/planning model."""
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

    # State: (mode, location_or_knot, current_npc)
    # mode: 'explore' or 'dialogue'
    start_state = ("explore", start_room, None)

    visited_states: set[tuple[str, str, str | None]] = set()
    queue = deque([start_state])

    while queue:
        mode, loc_or_knot, current_npc = queue.popleft()
        state = (mode, loc_or_knot, current_npc)
        if state in visited_states:
            continue
        visited_states.add(state)

        if mode == "explore":
            current_room = loc_or_knot
            # Transition 1: Move to connected room
            room_data = rooms.get(current_room, {})
            exits = room_data.get("exits", [])
            next_rooms = exits.values() if isinstance(exits, dict) else exits
            for next_room in next_rooms:
                if next_room in rooms:
                    next_state = ("explore", next_room, None)
                    if next_state not in visited_states:
                        queue.append(next_state)

            # Transition 2: Talk to NPC in current room
            for obj in room_data.get("objects", []):
                if obj == player_handle:
                    continue
                obj_name = obj if isinstance(obj, str) else next(iter(obj))
                if obj_name in npc_dialogue_graphs:
                    talk_state = ("dialogue", "__root__", obj_name)
                    if talk_state not in visited_states:
                        queue.append(talk_state)

        elif mode == "dialogue":
            current_knot = loc_or_knot
            npc = current_npc
            if npc and npc in npc_dialogue_graphs:
                graph = npc_dialogue_graphs[npc]
                targets = graph.get(current_knot, set())
                for target in targets:
                    if target in ("done", "END"):
                        # Return to explore mode in NPC's room
                        npc_room = game_objects.get(npc, {}).get("location", start_room)
                        next_state = ("explore", npc_room, None)
                        if next_state not in visited_states:
                            queue.append(next_state)
                    else:
                        next_state = ("dialogue", target, npc)
                        if next_state not in visited_states:
                            queue.append(next_state)

    # Calculate reachable rooms
    reachable_rooms = {s[1] for s in visited_states if s[0] == "explore"}
    unreachable_rooms = sorted(set(rooms.keys()) - reachable_rooms)

    # Check reachability for knots in reachable dialogues
    unreachable_knots: list[str] = []
    for npc, graph in npc_dialogue_graphs.items():
        # Check if NPC's dialogue was entered
        if any(s[0] == "dialogue" and s[2] == npc for s in visited_states):
            reachable_knots = {s[1] for s in visited_states if s[0] == "dialogue" and s[2] == npc}
            for knot_name in graph:
                if knot_name != "__root__" and knot_name not in reachable_knots:
                    unreachable_knots.append(f"{npc}:{knot_name}")

    if unreachable_rooms:
        print(f"Warning: unreachable rooms: {', '.join(unreachable_rooms)}")

    if unreachable_knots:
        print(f"Warning: unreachable dialogue knots: {', '.join(sorted(unreachable_knots))}")

    return unreachable_rooms


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
