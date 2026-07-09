from pathlib import Path
import sys

from runners.context_independent_actions import get_context_independent_actions
from runners.world import World


def get_game_dir() -> str:
    candidate = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    if candidate and (candidate / "world").exists():
        return str(candidate)
    return str(Path(__file__).resolve().parents[1])


if len(sys.argv) <= 1:
    sys.argv = [sys.argv[0], get_game_dir()]


def test_world_loads():
    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))
    world.load_world()

    assert world.current_room is not None
    assert len(world.world_state["rooms"]) > 0
    assert len(world.world_state["items"]) > 0


def test_player_can_pick_up_sword():
    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))
    world.load_world()

    # Whatever your inventory representation is.
    assert "sword" not in world.world_state["player"]["inventory"]

    actions = [
        ("t", "dave"),
        ("c", "-continue-"),
        ("c", "end dialogue"),
        ("g", "Blacksmith"),
        ("c", "Buy"),
        ("b", "sword"),
    ]
    for verb, target in actions:
        world.handle_action(verb, target)

    assert "sword" in world.world_state["player"]["inventory"]


def test_eve_blocks():

    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))
    world.load_world()

    actions = [
        ("g", "Eve's house"),
        ("c", "Fine."),
        ("c", "end dialogue"),
    ]
    for verb, target in actions:
        world.handle_action(verb, target)
    assert world.current_room == "red_town"
    world.handle_action("g", "Blacksmith")
    assert world.current_room == "red_smith"


def test_beat_bob():

    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))
    world.load_world()

    actions = [
        ("g", "Gate"),
        ("c", "Bring it on."),
        ("f", "Fight and win"),
        ("c", "end dialogue"),
    ]
    for verb, target in actions:
        world.handle_action(verb, target)
    assert world.world_state["game_objects"]["bob"]["money"] == 0
    assert world.world_state["game_objects"]["zorro"]["money"] == 10


def test_quests_load():
    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))

    assert "alice_flower" in world.world_state["quests"]
    assert world.world_state["quests"]["alice_flower"]["stage"] == 0
    assert world.world_state["quests"]["alice_flower"]["name"] == "A flower for Alice"


def test_alice_flower_quest_triggers():
    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))

    world.set_state("quests.alice_flower.stage", 10)
    world.world_state["game_objects"]["bob"]["accosts"] = False
    world.handle_action("g", "Gate")
    assert world.current_room == "field"
    assert world.world_state["quests"]["alice_flower"]["stage"] == 20

    world.handle_action("a", "flower")
    assert "flower" in world.world_state["player"]["inventory"]
    assert world.world_state["quests"]["alice_flower"]["stage"] == 30


def test_active_quest_log_lists_only_nonzero_stages():
    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))

    world.set_state("quests.alice_flower.stage", 10)

    entries = world.get_quest_log_entries()

    assert len(entries) == 1
    assert entries[0]["name"] == "A flower for Alice"
    assert entries[0]["stage"] == 10
    assert entries[0]["complete"] is False


def test_context_independent_actions_follow_game_config():
    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))

    world.game_settings["context_independent_actions"] = ["quit", "inventory"]

    actions = get_context_independent_actions(world)

    assert [action["id"] for action in actions] == ["quit", "inventory"]
