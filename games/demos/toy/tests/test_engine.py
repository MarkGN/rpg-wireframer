from pathlib import Path
from sys import argv
from runners.world import World


def test_world_loads():
    game_dir = argv[1]
    world = World(Path(f"{game_dir}"))
    world.load_world()

    assert world.current_room is not None
    assert len(world.rooms) > 0
    assert len(world.items) > 0


def test_player_can_pick_up_sword():
    game_dir = argv[1]
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
    
    game_dir = argv[1]
    world = World(Path(f"{game_dir}"))
    world.load_world()

    
    actions = [
        ("g", "Eve's house"),
        ("c", "Fine."),
        ('c', 'end dialogue'),
    ]
    for verb, target in actions:
        world.handle_action(verb, target)
    assert world.current_room == "red_town"
    world.handle_action("g", "Blacksmith")
    assert world.current_room == "red_smith"