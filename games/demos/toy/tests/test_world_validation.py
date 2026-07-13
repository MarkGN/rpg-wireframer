from pathlib import Path
import textwrap

from validate.game_objects import validate_game_objects
from validate.rooms import validate_world


def test_validate_world_accepts_room_locations_and_exits(tmp_path: Path) -> None:
    world_dir = tmp_path / "world"
    (world_dir / "rooms").mkdir(parents=True)
    (world_dir / "game_objects").mkdir(parents=True)

    (world_dir / "game.yaml").write_text(
        textwrap.dedent(
            """
            player: hero
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (world_dir / "game_objects" / "hero.yaml").write_text(
        textwrap.dedent(
            """
            name: Hero
            location: start
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    nested_dir = world_dir / "game_objects" / "nested"
    nested_dir.mkdir(parents=True)
    (nested_dir / "npc.yaml").write_text(
        textwrap.dedent(
            """
            name: NPC
            location:
              - start
              - middle
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    nested_room_dir = world_dir / "rooms" / "nested"
    nested_room_dir.mkdir(parents=True)
    (nested_room_dir / "start.yaml").write_text(
        textwrap.dedent(
            """
            name: Start
            exits:
              - middle
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (world_dir / "rooms" / "middle.yaml").write_text(
        textwrap.dedent(
            """
            name: Middle
            exits: []
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    validate_world(tmp_path)


def test_validate_game_objects_requires_metadata_and_dialogue(tmp_path: Path) -> None:
    world_dir = tmp_path / "world"
    (world_dir / "items").mkdir(parents=True)
    (world_dir / "rooms").mkdir(parents=True)
    (world_dir / "game_objects").mkdir(parents=True)
    (tmp_path / "dialogue").mkdir(parents=True)

    (world_dir / "game.yaml").write_text(
        textwrap.dedent(
            """
            player: hero
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (world_dir / "rooms" / "start.yaml").write_text(
        textwrap.dedent(
            """
            name: Start
            exits: []
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (world_dir / "game_objects" / "hero.yaml").write_text(
        textwrap.dedent(
            """
            name: Hero
            description: The main character.
            location: start
            inventory:
              - sword
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (world_dir / "items" / "sword.yaml").write_text(
        textwrap.dedent(
            """
            name: Sword
            description: A sharp blade.
            location: start
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "dialogue" / "hero.ink").write_text("Hello.\n")

    validate_game_objects(tmp_path)
