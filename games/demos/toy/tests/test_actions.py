from pathlib import Path

from runners.action import Action, InteractType, render_action
from runners.world import World


def test_render_action_uses_game_object_name_and_prompt() -> None:
    game_dir = Path(__file__).resolve().parents[1]
    world = World(game_dir)
    world.current_room = "cave"

    action = Action(InteractType.TALK, "chest_1")

    assert render_action(world, action) == "Open Treasure chest"


def test_render_action_uses_go_to_for_room_exits() -> None:
    game_dir = Path(__file__).resolve().parents[1]
    world = World(game_dir)
    world.current_room = "red_town"

    action = Action(InteractType.GO_TO, "Gate")

    assert render_action(world, action) == "Go to Gate"
