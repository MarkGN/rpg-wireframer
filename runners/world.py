from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .context import Context
    from .factory import ContextFactory


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
        self.game_path = game_path
        world_dir = game_path / "world"
        self.rooms_dir: Path = world_dir / "rooms"
        self.game_objects_dir: Path = world_dir / "game_objects"
        self.items_dir: Path = world_dir / "items"
        self.game_file: Path = world_dir / "game.yaml"
        self.flags_file: Path = world_dir / "flags.yaml"
        self.quests_dir: Path = world_dir / "quests"
        self.scenarios_file: Path = world_dir / "scenarios"

        self.world_state: dict[str, Any] = defaultdict(dict)
        self.player_handle: str = ""
        self.context_stack: list[Context] = []
        self.context_factory: ContextFactory | None = None
        self.current_room: str = None
        self.game_settings: dict[str, Any] = {}
        self.load_world()

    def load_world(self) -> None:
        """Load all yaml files."""

        # Rooms
        for path in sorted(self.rooms_dir.rglob("*.yaml")):
            room_id = path.stem
            data = load_yaml(path)
            data.setdefault("items", [])
            self.world_state["rooms"][room_id] = data

        # Items
        for path in sorted(self.items_dir.rglob("*.yaml")):
            item_id = path.stem
            data = load_yaml(path)
            self.world_state["items"][item_id] = data

        # Game Objects such as NPCs
        for path in sorted(self.game_objects_dir.rglob("*.yaml")):
            npc_id = path.stem
            data = load_yaml(path)

            state: dict = {}
            for key, value in data.items():
                state[key] = value

            state.setdefault("accosts", False)
            state.setdefault("dialogue", f"{npc_id}.ink")
            state.setdefault("is_visible", True)

            self.world_state["game_objects"][npc_id] = state

        # Quests
        for path in sorted(self.quests_dir.rglob("*.yaml")):
            quest_id = path.stem
            data = load_yaml(path)

            state: dict = {}
            for key, value in data.items():
                state[key] = value

            state.setdefault("stage", 0)
            self.world_state["quests"][quest_id] = state

        # Global flags
        if self.flags_file.exists():
            self.flags = load_yaml(self.flags_file)
            self.world_state["global"].update(self.flags)

        # PC
        game_data = load_yaml(self.game_file)
        self.player_handle = game_data["player"]
        self.game_settings = game_data.get("settings", {})
        player_path = None
        for path in sorted(self.game_objects_dir.rglob("*.yaml")):
            if path.stem == self.player_handle:
                player_path = path
                break
        if player_path is None:
            sys.exit(
                f"Error: player '{self.player_handle}' not found in world/game_objects/."
            )
        pc_data = load_yaml(player_path)
        self.world_state["player"] = {
            "name": pc_data.get("name", "Player"),
            "inventory": list(pc_data.get("inventory", [])),
            "money": pc_data.get("money", 0),
        }

        location = pc_data.get("location")
        if location not in self.world_state["rooms"]:
            sys.exit(f"Error: PC location '{location}' not found in world/rooms/.")
        from .factory import ContextFactory

        self.context_factory = ContextFactory()
        self.push_context(context="explore")
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
        for npc_id, meta in self.world_state["game_objects"].items():
            loc = meta.get("location", [])
            if isinstance(loc, str) and loc == self.current_room:
                present.append(npc_id)
            elif isinstance(loc, list) and self.current_room in loc:
                present.append(npc_id)
        return present

    def display_room(self) -> None:
        output = dict()
        room = self.world_state["rooms"][self.current_room]
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
            if self.world_state["game_objects"][npc_id].get("accosts", False):
                return npc_id
        return None

    def check_quest_triggers(self, event: str, target: str) -> None:
        """Advance quest stages when a trigger's conditions match."""
        for quest in self.world_state["quests"].values():
            current_stage = quest.get("stage", 0)
            for trigger in quest.get("triggers", []):
                when = trigger.get("when", {})
                if when.get("stage") != current_stage:
                    continue
                if when.get("event") != event:
                    continue
                if when.get("target") != target:
                    continue
                set_stage = trigger.get("set_stage")
                if set_stage is not None:
                    quest["stage"] = set_stage

    def check_block(self, category, target) -> str | None:
        """Return the first accosting NPC, if any"""
        for npc_id in self.npcs_in_room():
            guards = self.world_state["game_objects"][npc_id].get(
                "guards_" + category, {}
            )
            if target in [self.world_state["rooms"][g]["name"] for g in guards]:
                return npc_id
        return None

    def get_actions(self) -> list[tuple[str, str]]:
        """Return a list of valid actions."""
        return self.get_context().actions(self)

    def get_quest_log_entries(self) -> list[dict[str, Any]]:
        """Return active quests with their current stage and completion state."""
        entries = []
        for quest_id, quest in self.world_state.get("quests", {}).items():
            stage = quest.get("stage", 0)
            if stage == 0:
                continue
            stages = quest.get("stages", {})
            complete = stage >= max(stages.keys(), default=0)
            entries.append(
                {
                    "id": quest_id,
                    "name": quest.get("name", quest_id),
                    "stage": stage,
                    "complete": complete,
                }
            )
        return entries

    def handle_action(self, verb: str | object, target: str | None = None) -> None:
        if hasattr(verb, "interact_type") and hasattr(verb, "target"):
            action = verb
            self.get_context().apply(action.interact_type, action.target, self)
            return
        self.get_context().apply(verb, target, self)

    def get_context(self) -> Context:
        return self.context_stack[-1]

    def push_context(self, context: str, scenario="None", npc=None) -> None:
        ctx = self.context_factory.create(context, scenario, npc)
        self.context_stack.append(ctx)
        ctx.on_enter(self)

    def push_scenario(self, script: str, npc: str) -> None:
        scenario = load_yaml(self.scenarios_file / f"{script}.yaml")
        self.push_context(scenario["context"], scenario, npc)

    def pop_context(self, **kwargs) -> Context:
        last = self.context_stack.pop()
        self.context_stack[-1].on_resume(self, **kwargs)
        return last
