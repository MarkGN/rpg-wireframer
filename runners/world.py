"""
runner_text.py — text-mode runner for the RPG wireframe engine.

World layout expected:
    world/
        pc.yaml
        flags.yaml          (optional)
        rooms/              *.yaml
        npcs/               *.yaml
        items/              *.yaml  (optional, for room item definitions)
    dialogue/               *.ink   (compiled to *.ink.json by inklecate)

Each room yaml:
    name: The Rusty Flagon
    description: A dimly lit tavern.
    exits:
        north: back_alley
        south: market_square
    items:
        - old_lamp
    npcs:               # static residents; events can add/remove at runtime
        - innkeeper

Each NPC yaml (flat; unknown fields become world_state variables):
    name: Dave
    description: Dave is a handsome guy.
    portrait: null          # ignored in text mode
    location: red-town      # starting room key
    dialogue: dave.ink      # relative to dialogue/
    accosts: false          # true → triggers immediately on room entry
    hp: 3
    damage: 1
    money: 200
    has_met_player: false

pc.yaml:
    name: Alex
    location: tavern
    stats:
        money: 20
    inventory:
        - old_lamp
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
# Paths
# ---------------------------------------------------------------------------

WORLD_DIR: str = Path("world")
ROOMS_DIR: str = WORLD_DIR / "rooms"
NPCS_DIR: str = WORLD_DIR / "npcs"
ITEMS_DIR: str = WORLD_DIR / "items"
PC_FILE: str = WORLD_DIR / "pc.yaml"
FLAGS_FILE: str = WORLD_DIR / "flags.yaml"

# Fields that are engine keywords and should NOT be dumped into world_state.
NPC_KEYWORDS = {
    "name",
    "description",
    "portrait",
    "location",
    "locations",
    "dialogue",
    "accosts",
    "guards-exits",
    "guards-items",
    "inventory",
}


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
    def __init__(self):
        self.world_state: dict[str, Any] = defaultdict(dict)
        self.flag: dict[str, Any] = defaultdict(dict)
        self.rooms: dict[str, dict] = {}  # room_id → room data
        self.items: dict[str, dict] = {}  # item_id  → item data
        self.npcs: dict[str, dict] = {}  # npc_id  → npc metadata
        self.visited: set[str] = set()  # room_ids the player has entered
        self.context_stack: list[Context] = []
        self.context_factory: ContextFactory = None
        self.current_room: str = None
        self.load_world()

    def load_world(self) -> None:
        """Load all yaml files."""

        # Rooms
        for path in sorted(ROOMS_DIR.glob("*.yaml")):
            room_id = path.stem
            data = load_yaml(path)
            self.rooms[room_id] = data
            self.world_state["global"].setdefault(f"visited_{room_id}", False)

        # Items
        for path in sorted(ITEMS_DIR.glob("*.yaml")):
            item_id = path.stem
            data = load_yaml(path)
            self.items[item_id] = data

        # NPCs
        for path in sorted(NPCS_DIR.glob("*.yaml")):
            npc_id = path.stem
            data = load_yaml(path)

            # Split keywords from game-specific variables.
            meta: dict = {}
            state: dict = {}
            for key, value in data.items():
                if key in NPC_KEYWORDS:
                    meta[key] = value
                else:
                    state[key] = value

            # Normalise locations: accept either `location: x` or `locations: [x, y]`
            if "location" in meta and "locations" not in meta:
                meta["locations"] = [meta.pop("location")]
            elif "locations" not in meta:
                meta["locations"] = []

            meta.setdefault("accosts", False)
            meta.setdefault("dialogue", f"{npc_id}.ink")

            self.npcs[npc_id] = meta
            self.world_state[npc_id] = state

        # Global flags
        if FLAGS_FILE.exists():
            self.flags = load_yaml(FLAGS_FILE)
            self.world_state["global"].update(self.flags)

        # PC
        pc_data = load_yaml(PC_FILE)
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
        value = self.npcs if terms[-1] in NPC_KEYWORDS else self.world_state
        for term in terms:
            value = value[term]
        return value

    def set_state(self, key, value):
        terms = key.split(".")
        d = self.npcs if terms[-1] in NPC_KEYWORDS else self.world_state
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
        for npc_id, meta in self.npcs.items():
            if self.current_room in meta["locations"]:
                present.append(npc_id)
        return present

    def display_room(self) -> None:
        output = dict()
        room = self.rooms[self.current_room]
        first_visit = output["first_visit"] = self.current_room not in self.visited
        if first_visit:
            self.visited.add(self.current_room)
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
            if self.npcs[npc_id].get("accosts", False):
                return npc_id
        return None

    def check_block(self, category, target) -> str | None:
        """Return the first accosting NPC, if any"""
        for npc_id in self.npcs_in_room():
            guards = self.npcs[npc_id].get("guards-" + category, {})
            if target in guards:
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
