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

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from inkpython import Story

import yaml  # pip install pyyaml


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

WORLD_DIR   = Path("world")
ROOMS_DIR   = WORLD_DIR / "rooms"
NPCS_DIR    = WORLD_DIR / "npcs"
ITEMS_DIR   = WORLD_DIR / "items"
PC_FILE     = WORLD_DIR / "pc.yaml"
FLAGS_FILE  = WORLD_DIR / "flags.yaml"
DIALOGUE_DIR = Path("dialogue")

# Fields that are engine keywords and should NOT be dumped into world_state.
NPC_KEYWORDS = {"name", "description", "portrait", "location", "locations",
                "dialogue", "accosts", "guards-exits", "guards-items"}


# ---------------------------------------------------------------------------
# Ink integration
# ---------------------------------------------------------------------------

def ink_json_path(ink_filename: str) -> Path | None:
    """Return path to compiled .ink.json, compiling with inklecate if needed."""
    ink_path = DIALOGUE_DIR / ink_filename
    json_path = ink_path.with_suffix(".ink.json")

    if not ink_path.exists():
        print(f"[engine] Dialogue file not found: {ink_path}")
        return None

    # Recompile if source is newer than compiled output.
    if not json_path.exists() or ink_path.stat().st_mtime > json_path.stat().st_mtime:
        result = subprocess.run(
            ["inklecate", "-o", str(json_path), str(ink_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[debug] inklecate return code: {result.returncode}")
            print(f"[debug] stdout: {result.stdout}")
            print(f"[debug] stderr: {result.stderr}")
            print(f"[debug] json expected at: {json_path}")
            print(f"[debug] json exists: {json_path.exists()}")
            return None

    return json_path

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
        self.rooms:  dict[str, dict] = {}   # room_id → room data
        self.items:   dict[str, dict] = {}   # item_id  → item data
        self.npcs:   dict[str, dict] = {}   # npc_id  → npc metadata
        self.visited: set[str] = set()      # room_ids the player has entered
        self.current_room: str = self.load_world()
        self.dialogue_partner: str | None = None
        self.story: Story | None = None
        self.last_story_text: str | None = None


    def load_world(self) -> None:
        """Load all yaml files; return the player's location id."""

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
            "name":      pc_data.get("name", "Player"),
            "inventory": list(pc_data.get("inventory", [])),
            "money":      pc_data.get("money", 0)
        }

        location = pc_data.get("location")
        if location not in self.rooms:
            sys.exit(f"Error: PC location '{location}' not found in world/rooms/.")
        return location


    def npcs_in_room(self, room_id: str) -> list[str]:
        """Return npc_ids whose current location includes this room."""
        present = []
        for npc_id, meta in self.npcs.items():
            if room_id in meta["locations"]:
                present.append(npc_id)
        return present


    def move_npc(self, npc_id: str, new_location: str) -> None:
        """Move an NPC to a single new location (called from Ink or events)."""
        if npc_id not in self.npcs:
            print(f"[engine] Unknown NPC: {npc_id}")
            return
        self.npcs[npc_id]["locations"] = [new_location]


    def display_room(self) -> None:
        output = dict()
        room = self.rooms[self.current_room]
        first_visit = output["first_visit"] = self.current_room not in self.visited
        if first_visit:
            self.visited.add(self.current_room)
        output["handle"] = self.current_room
        output["name"] = room.get('name', self.current_room)
        output["description"] = room.get("description", "")
        output["npcs"] = self.npcs_in_room(self.current_room)
        output["items"] = room.get("items", [])
        output["exits"] = room.get("exits", {})
        return output


    def check_accost(self) -> str | None:
        """Return the first accosting NPC in this room, if any."""
        for npc_id in self.npcs_in_room(self.current_room):
            if self.npcs[npc_id].get("accosts", False):
                return npc_id
        return None

    def check_block(self, category, target) -> str | None:
        """Return the first accosting NPC, if any"""
        for npc_id in self.npcs_in_room(self.current_room):
            guards = self.npcs[npc_id].get("guards-"+category, {})
            if target in guards:
                return npc_id
        return None
    
    def get_actions(self):
        """Return a list of valid actions."""
        if self.dialogue_partner and self.story and (self.story.canContinue or self.story.currentChoices):
            if self.story.canContinue:
                return [("c", "-continue-")]
            elif self.story.currentChoices:
                return [("c",choice.text) for choice in self.story.currentChoices]
        else:
            locs = [("g",location) for location in self.rooms[self.current_room]["exits"]]
            present_npcs = [("t",npc) for npc in self.npcs_in_room(self.current_room)]
            items = [("a",item) for item in self.rooms[self.current_room]["items"]]
            options = locs + present_npcs + items
            return options
        
    def handle_action(self, action: str, target: str):
        if self.story:
            if self.story.canContinue:
                lines = []
                while self.story.canContinue:
                    lines.append(self.story.Continue().strip())
                self.last_story_text = "\n".join(lines)
            elif self.story.currentChoices:
                ix = [c.text for c in self.story.currentChoices].index(target)
                self.story.ChooseChoiceIndex(ix)
                self.last_story_text = self.story.Continue().strip()
            if not (self.story.canContinue or self.story.currentChoices):
                # self.dialogue_partner = None
                self.story = None

        else:
            self.last_story_text = None
            if action == "g":
                # go to location
                exits = self.rooms[self.current_room].get("exits", {})
                if target in exits:
                    blocking = self.check_block("exits", target)
                    if blocking:
                        self.begin_conversation(blocking)
                        return
                    self.current_room = exits[target]
                    accosting = self.check_accost()
                    if accosting:
                        self.begin_conversation(accosting)
                        return
                else:
                    available = ", ".join(exits.keys()) if exits else "none"
                    print(f"  You can't go to {target}. Available exits: {available}")
            elif action == "t":
                # talk to npc
                self.begin_conversation(target)
            elif action == "a":
                # acquire item
                room_items = self.rooms[self.current_room].get("items", [])
                if target in room_items:
                    blocking = self.check_block("items", target)
                    if blocking:
                        self.begin_conversation(blocking)
                        return
                    room_items.remove(target)
                    self.world_state["player"].setdefault("inventory", []).append(target)
            else:
                return ValueError(f"Invalid action: {action} {target}")

    def begin_conversation(self, npc_id: str) -> None:
        """
        Begin an NPC's Ink story.

        External functions honoured:
            gain(target, key, amount)
            add(target, item)
            remove(target, item)
            has(target, item)   → int 0/1
            get(key)
            set(key, value)
            move(npc, location)
            shop(inventory)
        """
        self.dialogue_partner = npc_id
        meta = self.npcs.get(npc_id, {})
        json_path = ink_json_path(meta.get("dialogue", f"{npc_id}.ink"))
        if json_path is None:
            print(f"(No dialogue available for {meta.get('name', npc_id)}.)\n")
            return

        # --- load compiled story ---
        with open(json_path) as f:
            story_data = json.load(f)

        self.story = Story(story_data)

        # TODO this
        # # --- inject context variables ---
        # def try_set(var, value):    
        #     self.story.variablesState.set(var, value)

        # # try_set("player_money",   self.world_state["player"]["money"])
        # # try_set("npc_location",  self.current_room)

        # for key, value in self.world_state.get(npc_id, {}).items():
        #     try_set(npc_id + "." + key, value)

        # --- register external functions ---

        def ext_get(key):
            terms = key.split('.')
            value = self.world_state
            for term in terms:
                value = value[term]
            return value

        def ext_set(key, value):
            terms = key.split('.')
            d = self.world_state
            for term in terms[:-1]:
                d = d[term]
            d[terms[-1]] = value

        def ext_increase(key, value):
            terms = key.split('.')
            d = self.world_state
            for term in terms[:-1]:
                d = d[term]
            d[terms[-1]] += value

        def ext_has_item(key, item) -> int:
            terms = key.split('.')
            value = self.world_state
            for term in terms:
                value = value[term]
            return item in value

        def ext_add_item(key, item):
            terms = key.split('.')
            d = self.world_state
            for term in terms[:-1]:
                d = d[term]
            d[terms[-1]].append(item)

        def ext_remove_item(key, item):
            terms = key.split('.')
            d = self.world_state
            for term in terms[:-1]:
                d = d[term]
            if item in d[terms[-1]]:
                d[terms[-1]].remove(item)

        def ext_at_npc(npc, location):
            return npc in self.npcs_in_room(location)

        def ext_move_npc(npc, location):
            self.move_npc(npc, location)

        def ext_shop(sales_inventory_handle):
            while True:
                sales_inventory = ext_get(sales_inventory_handle)
                if not sales_inventory:
                    print("Sorry, I'm out of stock.")
                    return
                print("\n  What would you like to buy?")
                print(f"You have ${ext_get('player.money')}.")
                for i, item_handle in enumerate(sales_inventory, 1):
                    print(f'  {i}. {self.items[item_handle]["name"]} — ${self.items[item_handle]["price"]}')
                print("  0. Leave")
                choice = input("  > ").strip()
                if choice == "0":
                    break
                if choice.isdigit() and 1 <= int(choice) <= len(sales_inventory):
                    item_handle = sales_inventory[int(choice) - 1]
                    item = self.items[item_handle]
                    price = item["price"]
                    if self.world_state["player"]["money"] >= price:
                        self.world_state["player"]["money"] -= price
                        ext_add_item("player.inventory", item_handle)
                        print(f"  You buy the {item["name"]} for ${price}.")
                    else:
                        print("  You can't afford that.")
                else:
                    print("  Invalid choice.")


        self.story.BindExternalFunction("get",          ext_get)
        self.story.BindExternalFunction("set",          ext_set)
        self.story.BindExternalFunction("increase",     ext_increase)
        self.story.BindExternalFunction("add",          ext_add_item)
        self.story.BindExternalFunction("remove",       ext_remove_item)
        self.story.BindExternalFunction("has",          ext_has_item)
        self.story.BindExternalFunction("move",         ext_move_npc)
        self.story.BindExternalFunction("at",           ext_at_npc)
        self.story.BindExternalFunction("shop",         ext_shop)

        self.step_story()

    def step_story(self) -> None:
        text = self.story.Continue().strip()
        if not text:
            self.step_story()
        self.last_story_text = text
        return
