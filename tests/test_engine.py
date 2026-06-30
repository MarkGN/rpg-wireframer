from runners.world import World


def test_world_loads():
    world = World()
    world.load_world()

    assert world.current_room is not None
    assert len(world.rooms) > 0
    assert len(world.items) > 0


def test_player_can_pick_up_sword():
    world = World()
    world.load_world()

    # Whatever your inventory representation is.
    assert "sword" not in world.world_state["player"]["inventory"]

    actions = [
        ("t", "dave"),
        ("c", "-continue-"),
        ("g", "Blacksmith"),
        ("c", "Buy"),
        "TODO: turns out shopping hasn't been properly decoupled yet, oops",
    ]
    for verb, target in actions:
        world.handle_action(verb, target)

    assert "sword" not in world.world_state["player"]["inventory"]
    # dave, continue, smith, buy, sword
