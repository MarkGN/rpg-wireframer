from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .context import Context
    from .action import Action
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
        self.context_factory: ContextFactory = ContextFactory()
        self.current_room: str = ""
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
        game_objects: dict[str, dict[str, Any]] = {}
        for path in sorted(self.game_objects_dir.rglob("*.yaml")):
            npc_id = path.stem
            data = load_yaml(path)

            state: dict = {}
            for key, value in data.items():
                state[key] = value

            state.setdefault("accosts", False)
            state.setdefault("dialogue", f"{npc_id}.ink")
            state.setdefault("inventory", [])
            state.setdefault("is_visible", True)
            state.setdefault("money", 0)

            game_objects[npc_id] = state

        # Populate room object references from room definitions first.
        # If the world is still using the old object.location model, infer room
        # placement from those values for backward compatibility.
        any_objects_defined = any(
            room_data.get("objects") is not None
            for room_data in self.world_state["rooms"].values()
        )
        if not any_objects_defined:
            for npc_id, meta in game_objects.items():
                location = meta.pop("location", None)
                if location is None:
                    continue
                if isinstance(location, str):
                    if location not in self.world_state["rooms"]:
                        sys.exit(
                            f"Error: object '{npc_id}' location '{location}' not found in world/rooms/."
                        )
                    self.world_state["rooms"][location].setdefault(
                        "objects", []
                    ).append(npc_id)
                elif isinstance(location, list):
                    for room_name in location:
                        if room_name not in self.world_state["rooms"]:
                            sys.exit(
                                f"Error: object '{npc_id}' location '{room_name}' not found in world/rooms/."
                            )
                        self.world_state["rooms"][room_name].setdefault(
                            "objects", []
                        ).append(npc_id)
                else:
                    sys.exit(
                        f"Error: object '{npc_id}' has invalid location value {location!r}"
                    )
        else:
            # Normalize objects lists for all rooms.
            for room_data in self.world_state["rooms"].values():
                room_data.setdefault("objects", [])
            for meta in game_objects.values():
                meta.pop("location", None)

        # Build the current active game object map from room placement.
        placed_objects: set[str] = set()
        for room_data in self.world_state["rooms"].values():
            for obj_handle in room_data.get("objects", []):
                if obj_handle not in game_objects:
                    sys.exit(
                        f"Error: room references unknown game object '{obj_handle}'."
                    )
                placed_objects.add(obj_handle)

        for obj_handle in sorted(placed_objects):
            self.world_state["game_objects"][obj_handle] = game_objects[obj_handle]

        # Quests
        for path in sorted(self.quests_dir.rglob("*.yaml")):
            quest_id = path.stem
            data = load_yaml(path)

            quest: dict = {}
            for key, value in data.items():
                quest[key] = value

            quest.setdefault("stage", 0)
            self.world_state["quests"][quest_id] = quest

        # Global flags
        if self.flags_file.exists():
            self.flags = load_yaml(self.flags_file)
            self.world_state["global"].update(self.flags)

        # PC
        game_data = load_yaml(self.game_file)
        self.player_handle = game_data["player"]
        self.game_settings = game_data.get("settings", {})
        if self.player_handle not in self.world_state["game_objects"]:
            sys.exit(
                f"Error: player '{self.player_handle}' not placed in any room in world/rooms/."
            )

        player_rooms = [
            room_id
            for room_id, room_data in self.world_state["rooms"].items()
            if self.player_handle in room_data.get("objects", [])
        ]
        if len(player_rooms) != 1:
            sys.exit(
                f"Error: player '{self.player_handle}' must be placed in exactly one room, found {len(player_rooms)}."
            )

        self.current_room = player_rooms[0]
        self.world_state["player"] = self.world_state["game_objects"][
            self.player_handle
        ]

        self.push_context(context="explore")

    def get_state(self, variable):
        terms = variable.split(".")
        value = self.world_state
        for term in terms:
            index = int(term) if term.isdigit() else term
            value = value[index]
        return value

    def set_state(self, variable, value):
        terms = variable.split(".")
        d = self.world_state
        for term in terms[:-1]:
            d = d[term]
        d[terms[-1]] = value

    def add_item(self, inventory, item):
        terms = inventory.split(".")
        d = self.world_state
        for term in terms[:-1]:
            d = d[term]
        d[terms[-1]].append(item)

    def transfer_all(self, donor_inventory, recipient_inventory):
        terms1 = donor_inventory.split(".")
        terms2 = recipient_inventory.split(".")
        d1 = self.world_state
        for term in terms1[:-1]:
            d1 = d1[term]
        d2 = self.world_state
        for term in terms2[:-1]:
            d2 = d2[term]
        d2[terms2[-1]].extend(d1[terms1[-1]])
        d1[terms1[-1]] = []

    def move_object(self, npc_id: str, from_room: str, to_room: str) -> None:
        if from_room not in self.world_state["rooms"]:
            raise ValueError(f"Unknown room '{from_room}'")
        if to_room not in self.world_state["rooms"]:
            raise ValueError(f"Unknown room '{to_room}'")

        from_objects = self.world_state["rooms"][from_room].setdefault("objects", [])
        to_objects = self.world_state["rooms"][to_room].setdefault("objects", [])

        if npc_id in from_objects:
            from_objects.remove(npc_id)
        if npc_id not in to_objects:
            to_objects.append(npc_id)

    def npcs_in_room(self) -> list[str]:
        """Return npc_ids currently present in the active room."""
        present = []
        for npc_id in self.world_state["rooms"][self.current_room].get("objects", []):
            if npc_id == self.player_handle:
                continue
            npc_data = self.world_state["game_objects"].get(npc_id, {})
            if npc_data.get("is_visible", True):
                present.append(npc_id)
        return present

    def display_room(self) -> dict[str, Any]:
        output: dict[str, Any] = dict()
        room = self.world_state["rooms"][self.current_room]
        output["handle"] = self.current_room
        output["name"] = room.get("name", self.current_room)
        output["description"] = room.get("description", "")
        output["npcs"] = self.npcs_in_room()
        output["items"] = room.get("items", [])
        output["exits"] = room.get("exits", [])
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

    def check_block(self, category: str, target: str) -> str | None:
        """Return the first accosting NPC guarding this target, if any."""
        current_room_data = self.world_state["rooms"].get(self.current_room, {})

        target_file_pointer = target
        target_room_name = None

        if category == "exits":
            exits = current_room_data.get("exits", {})
            exit_data = None
            if isinstance(exits, dict):
                exit_data = exits.get(target)
            elif isinstance(exits, list):
                for exit_item in exits:
                    if isinstance(exit_item, dict) and target in exit_item:
                        exit_data = exit_item[target]
                        break
                    elif isinstance(exit_item, str) and exit_item == target:
                        exit_data = exit_item
                        break

            if exit_data is not None:
                if isinstance(exit_data, str):
                    target_file_pointer = exit_data
                elif isinstance(exit_data, dict):
                    target_file_pointer = exit_data.get("room", target)

            if target_file_pointer in self.world_state["rooms"]:
                target_room_name = self.world_state["rooms"][target_file_pointer].get(
                    "name"
                )
        elif category == "items":
            if target in self.world_state["items"]:
                target_room_name = self.world_state["items"][target].get("name")

        for npc_id in self.npcs_in_room():
            npc_data = self.world_state["game_objects"].get(npc_id, {})
            guards_raw = npc_data.get("guards_" + category)
            if guards_raw is None and category.endswith("s"):
                guards_raw = npc_data.get("guards_" + category[:-1])

            if guards_raw is None:
                continue

            if isinstance(guards_raw, str):
                guards_list = [guards_raw]
            elif isinstance(guards_raw, list):
                guards_list = guards_raw
            elif isinstance(guards_raw, dict):
                guards_list = list(guards_raw.keys())
            else:
                guards_list = []

            for g in guards_list:
                if not isinstance(g, str):
                    continue
                if g == target_file_pointer or g == target:
                    return npc_id
                if target_room_name and g == target_room_name:
                    return npc_id
                if g in self.world_state["rooms"]:
                    g_room_name = self.world_state["rooms"][g].get("name")
                    if g_room_name and (
                        g_room_name == target or g_room_name == target_room_name
                    ):
                        return npc_id

        return None

    def get_actions(self) -> list[Action]:
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

    def handle_action(self, verb: str | None, target: str | None = None) -> None:
        if hasattr(verb, "interact_type") and hasattr(verb, "target"):
            action: Any = verb
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
