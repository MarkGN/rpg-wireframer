import shutil
import textwrap
from pathlib import Path

import pytest

from runners.action import InteractType
from runners.world import World


def test_exit_blocker_triggers_dialogue_and_pass(tmp_path: Path) -> None:
    if shutil.which("inklecate") is None:
        pytest.skip("inklecate is not installed")

    world_dir = tmp_path / "world"
    (world_dir / "rooms").mkdir(parents=True)
    (world_dir / "game_objects").mkdir(parents=True)
    (world_dir / "items").mkdir(parents=True)
    (tmp_path / "dialogue").mkdir(parents=True)

    (world_dir / "game.yaml").write_text("player: hero\n", encoding="utf-8")
    (world_dir / "game_objects" / "hero.yaml").write_text(
        "name: Hero\nlocation: myroom\ninventory: []\n", encoding="utf-8"
    )
    (world_dir / "game_objects" / "blue_lock.yaml").write_text(
        "name: Blue Lock\n", encoding="utf-8"
    )
    (world_dir / "rooms" / "myroom.yaml").write_text(
        textwrap.dedent(
            """
            name: My Room
            exits:
              Blue house: {room: blue_house, blocker: blue_lock}
              Abandoned shack: haunted_house
            items: []
            objects:
              - hero
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (world_dir / "rooms" / "blue_house.yaml").write_text(
        "name: Blue House\nexits: {}\nitems: []\nobjects: []\n", encoding="utf-8"
    )
    (world_dir / "rooms" / "haunted_house.yaml").write_text(
        "name: Haunted House\nexits: {}\nitems: []\nobjects: []\n", encoding="utf-8"
    )

    (tmp_path / "dialogue" / "globals.ink").write_text("EXTERNAL pass()\n")
    (tmp_path / "dialogue" / "blue_lock.ink").write_text(
        textwrap.dedent(
            """
            The door is locked tight.
            ~ pass()
            You unlock the door and walk through.
            -> END
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    world = World(tmp_path)
    assert "blue_lock" in world.world_state["game_objects"]
    assert world.current_room == "myroom"

    # Trying to go through the blocked exit triggers dialogue with blue_lock
    world.handle_action(InteractType.GO_TO, "Blue house")

    context = world.get_context()
    assert context.__class__.__name__ == "Dialogue"
    assert context.npc == "blue_lock"
    # Because pass() was called in blue_lock.ink, player is now in blue_house
    assert world.current_room == "blue_house"


def test_exit_blocker_unblocked_exit_moves_normally(tmp_path: Path) -> None:
    world_dir = tmp_path / "world"
    (world_dir / "rooms").mkdir(parents=True)
    (world_dir / "game_objects").mkdir(parents=True)
    (world_dir / "items").mkdir(parents=True)
    (tmp_path / "dialogue").mkdir(parents=True)

    (world_dir / "game.yaml").write_text("player: hero\n", encoding="utf-8")
    (world_dir / "game_objects" / "hero.yaml").write_text(
        "name: Hero\nlocation: myroom\ninventory: []\n", encoding="utf-8"
    )
    (world_dir / "rooms" / "myroom.yaml").write_text(
        textwrap.dedent(
            """
            name: My Room
            exits:
              Abandoned shack: haunted_house
            items: []
            objects:
              - hero
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (world_dir / "rooms" / "haunted_house.yaml").write_text(
        "name: Haunted House\nexits: {}\nitems: []\nobjects: []\n", encoding="utf-8"
    )

    world = World(tmp_path)
    assert world.current_room == "myroom"

    world.handle_action(InteractType.GO_TO, "Abandoned shack")
    assert world.current_room == "haunted_house"


def test_exit_blocker_unknown_blocker_exits(tmp_path: Path) -> None:
    world_dir = tmp_path / "world"
    (world_dir / "rooms").mkdir(parents=True)
    (world_dir / "game_objects").mkdir(parents=True)
    (world_dir / "items").mkdir(parents=True)

    (world_dir / "game.yaml").write_text("player: hero\n", encoding="utf-8")
    (world_dir / "game_objects" / "hero.yaml").write_text(
        "name: Hero\nlocation: myroom\ninventory: []\n", encoding="utf-8"
    )
    (world_dir / "rooms" / "myroom.yaml").write_text(
        textwrap.dedent(
            """
            name: My Room
            exits:
              Blue house: {room: blue_house, blocker: missing_lock}
            items: []
            objects:
              - hero
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (world_dir / "rooms" / "blue_house.yaml").write_text(
        "name: Blue House\nexits: {}\nitems: []\nobjects: []\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as exc:
        World(tmp_path)
    assert "missing_lock" in str(exc.value)
