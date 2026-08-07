from pathlib import Path
import shutil
import sys

import pytest

from runners.context_independent_actions import get_context_independent_actions
from runners.contexts.dialogue import find_ink_path, ink_json_path
from runners.world import World
from runners.binder import Binder


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

    assert "sword" not in world.get_state(
        Binder({"player": world.player_handle}).apply("$player.inventory")
    )

    actions = [
        ("t", "dave"),
        ("c", "-continue-"),
        ("c", "end dialogue"),
        ("g", "Blacksmith"),
        ("t", "charlie"),
        ("c", "Buy"),
        ("b", "sword"),
    ]
    for verb, target in actions:
        world.handle_action(verb, target)

    assert "sword" in world.get_state(
        Binder({"player": world.player_handle}).apply("$player.inventory")
    )


def test_eve_blocks():

    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))
    world.load_world()

    actions = [
        ("g", "Eve's house"),
        ("c", "-continue-"),
        ("c", "-continue-"),
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


def test_find_ink_path_searches_nested_directories(tmp_path):
    dialogue_dir = tmp_path / "dialogue" / "friends" / "boys"
    dialogue_dir.mkdir(parents=True)
    nested_file = dialogue_dir / "jim.ink"
    nested_file.write_text("// test ink file")

    found = find_ink_path("jim.ink", tmp_path / "dialogue")

    assert found == nested_file
    assert find_ink_path("friends/boys/jim.ink", tmp_path / "dialogue") == nested_file


def test_ink_json_path_compiles_nested_ink_with_globals_include(tmp_path):
    if shutil.which("inklecate") is None:
        pytest.skip("inklecate is not installed")

    dialogue_dir = tmp_path / "dialogue"
    nested_dir = dialogue_dir / "golden_route" / "girls"
    nested_dir.mkdir(parents=True)

    globals_file = dialogue_dir / "globals.ink"
    globals_file.write_text("// helper functions\n")

    nested_file = nested_dir / "jenny.ink"
    nested_file.write_text("Hello.\n-> END\n")

    compiled_json = ink_json_path("jenny.ink", dialogue_dir)

    assert compiled_json is not None
    assert compiled_json.exists()


def test_speaker_chiming_in():
    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))
    world.load_world()

    # Manually start talking to Bob
    world.handle_action("t", "eve")

    context = world.get_context()
    assert context.current_speaker == "eve"
    assert context.last_text == "Hi! Sorry, but you can't come in here."

    # Verify that the action is to continue talking
    actions = context.actions(world)
    assert len(actions) == 1
    assert actions[0].interact_type == "cont_talk"
    assert actions[0].target == "-continue-"

    # Continue the dialogue
    world.handle_action("c", "-continue-")

    # Verify that the speaker transitioned to Alice and the text updated
    assert context.current_speaker == "dave"
    assert context.last_text == "You suck!"

    # Say fine
    world.handle_action("c", "-continue-")
    world.handle_action("c", "Fine.")

    # Verify that the dialogue can now be ended
    actions = context.actions(world)
    assert len(actions) == 1
    assert actions[0].interact_type == "end_dialogue"

    # End the dialogue
    world.handle_action("c", "end dialogue")

    # Ensure we are back in the Explore context
    assert world.get_context().__class__.__name__ == "Explore"


def test_check_block_file_pointer():
    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))
    world.load_world()

    world.world_state["game_objects"]["guard"] = {
        "name": "Guard",
        "guards_exit": ["house"],
    }
    world.world_state["rooms"]["street"] = {
        "name": "Street",
        "exits": {"Red house": "house"},
        "items": [],
        "objects": ["guard"],
    }
    world.world_state["rooms"]["house"] = {
        "name": "Jenny's house",
        "exits": {},
        "items": [],
    }

    world.current_room = "street"

    blocking = world.check_block("exits", "Red house")
    assert blocking == "guard"


def test_dialogue_bad_external_call_returns_line_number():
    game_dir = get_game_dir()
    world = World(Path(f"{game_dir}"))
    world.load_world()

    dialogue_dir = Path(game_dir) / "dialogue"
    bad_ink_file = dialogue_dir / "bad_call_test.ink"
    bad_ink_file.write_text(
        "Hello world\n~ increase('non_existent_object.money', 5)\n-> END\n",
        encoding="utf-8",
    )

    try:
        world.world_state["game_objects"]["test_npc"] = {
            "name": "Test NPC",
            "ink": "bad_call_test",
        }
        world.push_context("dialogue", npc="test_npc")
    except Exception as exc:
        err_msg = str(exc)
        assert "line 2" in err_msg.lower()
        assert "increase" in err_msg
    finally:
        bad_ink_file.unlink(missing_ok=True)
        json_file = dialogue_dir / "bad_call_test.ink.json"
        json_file.unlink(missing_ok=True)


def test_dialogue_malformed_ink_returns_line_number():
    game_dir = get_game_dir()
    dialogue_dir = Path(game_dir) / "dialogue"
    bad_ink_file = dialogue_dir / "malformed_test.ink"
    bad_ink_file.write_text("Hello world\n-> non_existent_knot\n", encoding="utf-8")

    try:
        from runners.contexts.dialogue import ink_json_path

        ink_json_path("malformed_test.ink", dialogue_dir)
    except Exception as exc:
        err_msg = str(exc)
        assert "line 2" in err_msg.lower()
        assert "non_existent_knot" in err_msg
    finally:
        bad_ink_file.unlink(missing_ok=True)
        json_file = dialogue_dir / "malformed_test.ink.json"
        json_file.unlink(missing_ok=True)
