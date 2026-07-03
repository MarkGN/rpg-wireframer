"""
runner_text.py — text-mode runner for the RPG wireframe engine.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from typing import TYPE_CHECKING

from .factory import ContextFactory

if TYPE_CHECKING:
    from context import Context


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# World state
# ---------------------------------------------------------------------------


# world_state["player"]  — PC stats, inventory, flags
# world_state["<npc_id>"] — per-NPC variables (hp, money, flags, …)
# world_state["global"]  — room flags and anything not tied to an entity
class World:
    def __init__(self, game_path: Path):
        world_dir: Path = game_path / "world"
        self.rooms_dir: Path = world_dir / "rooms"
        self.game_objects_dir: Path = world_dir / "game_objects"
        self.items_dir: Path = world_dir / "items"
        self.pc_file: Path = world_dir / "pc.yaml"
        self.flags_file: Path = world_dir / "flags.yaml"

        self.world_state: dict[str, Any] = defaultdict(dict)
        self.flags: dict[str, Any] = defaultdict(dict)
        self.rooms: dict[str, dict] = {}  # room_id → room data
        self.items: dict[str, dict] = {}  # item_id  → item data
        self.context_stack: list[Context] = []
        self.context_factory: ContextFactory = None
        self.current_room: str = None
        self.load_world()

    def load_world(self) -> None:
        """Load all yaml files."""

        # Rooms
        for path in sorted(self.rooms_dir.glob("*.yaml")):
            room_id = path.stem
            data = load_yaml(path)
            data.setdefault("items", [])
            self.rooms[room_id] = data

        # Items
        for path in sorted(self.items_dir.glob("*.yaml")):
            item_id = path.stem
            data = load_yaml(path)
            self.items[item_id] = data

        # NPCs
        for path in sorted(self.game_objects_dir.glob("*.yaml")):
            print("path", path)
            npc_id = path.stem
            data = load_yaml(path)

            state: dict = {}
            for key, value in data.items():
                state[key] = value

            state.setdefault("accosts", False)
            state.setdefault("dialogue", f"{npc_id}.ink")
            state.setdefault("is_visible", True)

            self.world_state[npc_id] = state

        # Global flags
        if self.flags_file.exists():
            self.flags = load_yaml(self.flags_file)
            self.world_state["global"].update(self.flags)

        # PC
        pc_data = load_yaml(self.pc_file)
        self.world_state["player"] = {
            "name": pc_data.get("name", "Player"),
            "inventory": list(pc_data.get("inventory", [])),
            "money": pc_data.get("money", 0),
        }

        location = pc_data.get("location")
        if location not in self.rooms:
            sys.exit(f"Error: PC location '{location}' not found in world/rooms/.")
        self.context_factory = ContextFactory()
        self.push_context("explore")
        self.current_room = location

    def get_state(self, key):
        terms = key.split(".")
        value = self.world_state
        for term in terms:
            value = value[term]
        return value

    def set_state(self, key, value):
        terms = key.split(".")
        d = self.world_state
        for term in terms[:-1]:
            d = d[term]
        d[terms[-1]] = value

    def add_item(self, key, item):
        terms = key.split(".")
        d = self.world_state
        for term in terms[:-1]:
            d = d[term]
        d[terms[-1]].append(item)

    def npcs_in_room(self) -> list[str]:
        """Return npc_ids whose current location includes this room."""
        present = []
        for npc_id, meta in self.world_state.items():
            if self.current_room in meta.get("location",""):
                present.append(npc_id)
        return present

    def display_room(self) -> None:
        output = dict()
        room = self.rooms[self.current_room]
        output["handle"] = self.current_room
        output["name"] = room.get("name", self.current_room)
        output["description"] = room.get("description", "")
        output["npcs"] = self.npcs_in_room()
        output["items"] = room.get("items", [])
        output["exits"] = room.get("exits", {})
        return output

    def check_accost(self) -> str | None:
        """Return the first accosting NPC in this room, if any."""
        for npc_id in self.npcs_in_room():
            if self.world_state[npc_id].get("accosts", False):
                return npc_id
        return None

    def check_block(self, category, target) -> str | None:
        """Return the first accosting NPC, if any"""
        for npc_id in self.npcs_in_room():
            guards = self.world_state[npc_id].get("guards_" + category, {})
            if target in [self.rooms[g]["name"] for g in guards]:
                return npc_id
        return None

    def get_actions(self) -> list[tuple[str, str]]:
        """Return a list of valid actions."""
        return self.get_context().actions(self)

    def handle_action(self, verb: str, target: str) -> None:
        self.get_context().apply(verb, target, self)

    def get_context(self) -> Context:
        return self.context_stack[-1]

    def push_context(self, context: str, **kwargs) -> None:
        ctx = self.context_factory.create(context, **kwargs)
        self.context_stack.append(ctx)
        ctx.on_enter(self)

    def pop_context(self, **kwargs) -> Context:
        last = self.context_stack.pop()
        self.context_stack[-1].on_resume(self, **kwargs)
        return last
