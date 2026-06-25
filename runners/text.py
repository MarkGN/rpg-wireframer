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
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

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
# World state
# ---------------------------------------------------------------------------

# world_state["player"]  — PC stats, inventory, flags
# world_state["<npc_id>"] — per-NPC variables (hp, money, flags, …)
# world_state["global"]  — room flags and anything not tied to an entity
world_state: dict[str, Any] = defaultdict(dict)

# Metadata that the engine itself uses (not mutable from Ink).
rooms:  dict[str, dict] = {}   # room_id → room data
all_items:   dict[str, dict] = {}   # item_id  → item data
npcs:   dict[str, dict] = {}   # npc_id  → npc metadata
visited: set[str] = set()      # room_ids the player has entered


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_world() -> str:
    """Load all yaml files; return the player's location id."""

    # Rooms
    for path in sorted(ROOMS_DIR.glob("*.yaml")):
        room_id = path.stem
        data = load_yaml(path)
        rooms[room_id] = data
        world_state["global"].setdefault(f"visited_{room_id}", False)

    # Items
    for path in sorted(ITEMS_DIR.glob("*.yaml")):
        item_id = path.stem
        data = load_yaml(path)
        all_items[item_id] = data

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

        npcs[npc_id] = meta
        world_state[npc_id] = state

    # Global flags
    if FLAGS_FILE.exists():
        flags = load_yaml(FLAGS_FILE)
        world_state["global"].update(flags)

    # PC
    pc_data = load_yaml(PC_FILE)
    world_state["player"] = {
        "name":      pc_data.get("name", "Player"),
        "inventory": list(pc_data.get("inventory", [])),
        "money":      pc_data.get("money", 0)
    }

    location = pc_data.get("location")
    if location not in rooms:
        sys.exit(f"Error: PC location '{location}' not found in world/rooms/.")
    return location


# ---------------------------------------------------------------------------
# NPC presence
# ---------------------------------------------------------------------------

def npcs_in_room(room_id: str) -> list[str]:
    """Return npc_ids whose current location includes this room."""
    present = []
    for npc_id, meta in npcs.items():
        if room_id in meta["locations"]:
            present.append(npc_id)
    return present


def move_npc(npc_id: str, new_location: str) -> None:
    """Move an NPC to a single new location (called from Ink or events)."""
    if npc_id not in npcs:
        print(f"[engine] Unknown NPC: {npc_id}")
        return
    npcs[npc_id]["locations"] = [new_location]


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
        print(f"[debug] inklecate return code: {result.returncode}")
        print(f"[debug] stdout: {result.stdout}")
        print(f"[debug] stderr: {result.stderr}")
        print(f"[debug] json expected at: {json_path}")
        print(f"[debug] json exists: {json_path.exists()}")
        if result.returncode != 0:
            print(f"[inklecate] {result.stderr}")
            return None

    return json_path


def run_ink_story(npc_id: str, room_id: str) -> None:
    """
    Run an NPC's Ink story in the terminal.

    Context variables injected into Ink:
        player_money, npc_location, <all npc world_state vars>

    External functions honoured:
        gain(target, key, amount)
        add_item(target, item)
        remove_item(target, item)
        has_item(target, item)   → int 0/1
        set_flag(key)
        clear_flag(key)
        check_flag(key)          → int 0/1
        move_npc(npc, location)
        shop(item, price, ...)
        combat(enemy, hp, damage, on_win, on_lose, on_run)
    """
    meta = npcs.get(npc_id, {})
    json_path = ink_json_path(meta.get("dialogue", f"{npc_id}.ink"))
    if json_path is None:
        print(f"(No dialogue available for {meta.get('name', npc_id)}.)\n")
        return

    # --- load compiled story ---
    with open(json_path) as f:
        story_data = json.load(f)

    # Lazy import: try inkpy, fall back gracefully.
    try:
        from inkpython import Story  # type: ignore
    except ImportError:
        print("[engine] inkpy not installed. Run: pip install inkpython")
        return

    story = Story(story_data)

    # --- inject context variables ---
    def try_set(var, value):
        try:
            story.variables_state[var] = value
        except Exception:
            pass  # variable not declared in .ink — that's fine

    try_set("player_money",   world_state["player"]["money"])
    try_set("npc_location",  room_id)

    for key, value in world_state.get(npc_id, {}).items():
        try_set(key, value)

    # --- register external functions ---



    def ext_get(key):
        terms = key.split('.')
        value = world_state
        for term in terms:
            value = value[term]
        return value

    def ext_set(key, value):
        terms = key.split('.')
        d = world_state
        for term in terms[:-1]:
            d = d[term]
        d[terms[-1]] = value

    def ext_increase(key, value):
        terms = key.split('.')
        d = world_state
        for term in terms[:-1]:
            d = d[term]
        d[terms[-1]] += value

    def ext_has_item(key, item) -> int:
        terms = key.split('.')
        value = world_state
        for term in terms:
            value = value[term]
        return item in value

    def ext_add_item(key, item):
        terms = key.split('.')
        d = world_state
        for term in terms[:-1]:
            d = d[term]
        d[terms[-1]].append(item)

    def ext_remove_item(key, item):
        terms = key.split('.')
        d = world_state
        for term in terms[:-1]:
            d = d[term]
        if item in d[terms[-1]]:
            d[terms[-1]].remove(item)

    def ext_at_npc(npc, location):
        return npc in npcs_in_room(location)

    def ext_move_npc(npc, location):
        move_npc(npc, location)

    def ext_shop(sales_inventory_handle):
        while True:
            sales_inventory = ext_get(sales_inventory_handle)
            if not sales_inventory:
                print("Sorry, I'm out of stock.")
                return
            print("\n  What would you like to buy?")
            print(f"You have ${ext_get('player.money')}.")
            for i, item_handle in enumerate(sales_inventory, 1):
                print(f'  {i}. {all_items[item_handle]["name"]} — ${all_items[item_handle]["price"]}')
            print("  0. Leave")
            choice = input("  > ").strip()
            if choice == "0":
                break
            if choice.isdigit() and 1 <= int(choice) <= len(sales_inventory):
                item_handle = sales_inventory[int(choice) - 1]
                item = all_items[item_handle]
                price = item["price"]
                if world_state["player"]["money"] >= price:
                    world_state["player"]["money"] -= price
                    ext_add_item("player.inventory", item_handle)
                    print(f"  You buy the {item["name"]} for ${price}.")
                else:
                    print("  You can't afford that.")
            else:
                print("  Invalid choice.")

    story.BindExternalFunction("get",         ext_get)
    story.BindExternalFunction("set",         ext_set)
    story.BindExternalFunction("increase",    ext_increase)
    story.BindExternalFunction("add",    ext_add_item)
    story.BindExternalFunction("remove", ext_remove_item)
    story.BindExternalFunction("has",    ext_has_item)
    story.BindExternalFunction("move",    ext_move_npc)
    story.BindExternalFunction("at",    ext_at_npc)
    story.BindExternalFunction("shop",        ext_shop)

    # --- story loop ---
    npc_name = meta.get("name", npc_id)
    print(f"\n{'─' * 40}")
    print(f"  {npc_name}")
    print(f"{'─' * 40}")

    while story.canContinue or story.currentChoices:
        while story.canContinue:
            text = story.Continue().strip()
            if not text:
                continue

            # Handle tags: portrait is ignored in text mode;
            # unknown tags are printed as stage directions.
            tags = story.currentTags or []
            stage_directions = []
            for tag in tags:
                key, _, value = tag.partition(":")
                key = key.strip().lower()
                value = value.strip()
                if key in ("portrait", "speaker"):
                    pass  # text mode ignores presentation tags
                elif key == "sfx":
                    pass  # likewise
                else:
                    stage_directions.append(f"[{tag.strip()}]")

            if stage_directions:
                print("  " + "  ".join(stage_directions))
            print(f"  {text}")

        if story.currentChoices:
            print()
            for i, choice in enumerate(story.currentChoices, 1):
                print(f"  {i}. {choice.text}")
            while True:
                raw = input("  > ").strip()
                if raw.isdigit() and 1 <= int(raw) <= len(story.currentChoices):
                    story.ChooseChoiceIndex(int(raw) - 1)
                    break
                print("  Please enter a number.")

    print(f"{'─' * 40}\n")

    # Write observable Ink variables back to world_state.
    # (inkpy exposes declared variables via variables_state)
    try:
        for key in story.variables_state:
            if key.startswith("player_"):
                field = key[len("player_"):]
                if field in world_state["player"]:
                    world_state["player"][field] = story.variables_state[key]
            elif key in world_state.get(npc_id, {}):
                world_state[npc_id][key] = story.variables_state[key]
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Room display
# ---------------------------------------------------------------------------

def display_room(room_id: str, force_description: bool = False) -> None:
    room = rooms[room_id]
    first_visit = room_id not in visited

    print(f"\n{'═' * 40}")
    print(f"  {room.get('name', room_id)}")
    print(f"{'═' * 40}")

    if first_visit or force_description:
        desc = room.get("description", "")
        if desc:
            print(f"  {desc}\n")
        visited.add(room_id)

    # NPCs
    present = npcs_in_room(room_id)
    if present:
        names = [npcs[n].get("name", n) for n in present]
        print(f"  People here: {', '.join(names)}")

    # Items
    room_items = room.get("items", [])
    if room_items:
        print(f"  Items: {', '.join(room_items)}")

    # Exits
    exits = room.get("exits", {})
    if exits:
        print(f"  Exits: {', '.join(exits.keys())}")

    print()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def print_help() -> None:
    print("""
  Commands:
    look / l            — describe the current room again
    inventory / i       — show inventory and money
    talk <name>         — talk to an NPC (partial name ok)
    go <direction>      — move to a connected room
    take <item>         — pick up an item from the room
    help / ?            — show this message
    quit / q            — exit
""")


def match_npc(name_fragment: str, room_id: str) -> str | None:
    """Find an NPC in the current room by partial name match."""
    fragment = name_fragment.lower()
    present = npcs_in_room(room_id)
    for npc_id in present:
        npc_name = npcs[npc_id].get("name", npc_id).lower()
        if fragment in npc_name or fragment in npc_id.lower():
            return npc_id
    return None


def check_accost(room_id: str) -> str | None:
    """Return the first accosting NPC in this room, if any."""
    for npc_id in npcs_in_room(room_id):
        if npcs[npc_id].get("accosts", False):
            return npc_id
    return None


def check_block(room_id, category, target):
    """Return the first accosting NPC, if any"""
    for npc_id in npcs_in_room(room_id):
        guards = npcs[npc_id].get("guards-"+category, {})
        if target in guards:
            return npc_id
    return None


def main() -> None:
    if not WORLD_DIR.exists():
        sys.exit("Error: 'world/' directory not found. Run from your game's root folder.")

    current_room = load_world()
    display_room(current_room)

    # Check for accosting NPCs on spawn.
    accosting = check_accost(current_room)
    if accosting:
        run_ink_story(accosting, current_room)

    while True:

        
        locs = [("Go to "+location, "go "+location) for location in rooms[current_room]["exits"]]
        present_npcs = [("Talk to "+npc, "t "+npc) for npc in npcs_in_room(current_room)]
        items = [("Take "+item, "take "+item) for item in rooms[current_room]["items"]]
        options = [("Describe", "look"), ("Inventory", "inventory")] + locs + present_npcs + items

        
        print("  0. Quit game")
        for i, option in enumerate(options, 1):
            print(f'  {i}. {option[0]}')
        choice = input("  > ").strip()
        if choice == "0":
            print("Goodbye.")
            break
        raw = options[int(choice)-1][1] if (choice.isdigit() and 1 <= int(choice) <= len(options)) else None
        if not raw:
            continue

        parts  = raw.split(None, 1)
        verb   = parts[0].lower()
        rest   = parts[1] if len(parts) > 1 else ""

        # --- look ---
        if verb == "look":
            display_room(current_room, force_description=True)

        # --- inventory ---
        elif verb == "inventory":
            inv = world_state["player"].get("inventory", [])
            money = world_state["player"].get("money", 0)
            print(f"\n  Money: {money}")
            print(f"  Inventory: {', '.join([all_items[item]["name"] for item in inv]) if inv else '(empty)'}\n")

        # --- go ---
        elif verb == "go":
            direction = rest.lower().strip()
            exits = rooms[current_room].get("exits", {})
            if direction in exits:
                blocking = check_block(current_room, "exits", direction)
                if blocking:
                    run_ink_story(blocking, current_room)
                    continue
                current_room = exits[direction]
                display_room(current_room)
                accosting = check_accost(current_room)
                if accosting:
                    run_ink_story(accosting, current_room)
            else:
                available = ", ".join(exits.keys()) if exits else "none"
                print(f"  You can't go {direction!r}. Available exits: {available}")

        # --- take ---
        elif verb == "take":
            item = rest.lower().strip()
            room_items = rooms[current_room].get("items", [])
            if item in room_items:
                blocking = check_block(current_room, "items", direction)
                if blocking:
                    run_ink_story(blocking, current_room)
                    continue
                room_items.remove(item)
                world_state["player"].setdefault("inventory", []).append(item)
                print(f"  You pick up the {item}.")
            else:
                print(f"  There's no {item!r} here.")

        # --- talk ---
        elif verb == "t":
            if not rest:
                present = npcs_in_room(current_room)
                if not present:
                    print("  There's nobody here to talk to.")
                elif len(present) == 1:
                    run_ink_story(present[0], current_room)
                else:
                    names = [npcs[n].get("name", n) for n in present]
                    print(f"  Talk to whom? ({', '.join(names)})")
            else:
                npc_id = match_npc(rest, current_room)
                if npc_id:
                    run_ink_story(npc_id, current_room)
                else:
                    print(f"  There's nobody called {rest!r} here.")

        else:
            print(f"  Unknown command {raw!r}. Type 'help' for a list of commands.")


if __name__ == "__main__":
    main()