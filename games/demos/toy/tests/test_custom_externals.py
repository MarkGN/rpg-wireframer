import shutil
import sys
import textwrap
from pathlib import Path

import pytest

from runners.contexts.dialogue import (
    ink_json_path,
    load_custom_externals_definitions,
)
from runners.world import World


def get_game_dir() -> str:
    candidate = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    if candidate and (candidate / "world").exists():
        return str(candidate)
    return str(Path(__file__).resolve().parents[1])


def test_loads_custom_externals_definitions(tmp_path: Path) -> None:
    dialogue_dir = tmp_path / "dialogue"
    dialogue_dir.mkdir(parents=True)
    (dialogue_dir / "custom_externals.yaml").write_text(
        textwrap.dedent(
            """
            portrait:
              args: 1
            music:
              args: 1
            sfx:
              args: 1
            """
        ).strip()
        + "\n"
    )

    defs = load_custom_externals_definitions(dialogue_dir)
    assert defs == {"portrait": 1, "music": 1, "sfx": 1}


def test_ink_json_path_includes_custom_externals(tmp_path: Path) -> None:
    if shutil.which("inklecate") is None:
        pytest.skip("inklecate is not installed")

    dialogue_dir = tmp_path / "dialogue"
    dialogue_dir.mkdir(parents=True)
    (dialogue_dir / "globals.ink").write_text("// helper functions\n")
    (dialogue_dir / "custom_externals.yaml").write_text(
        textwrap.dedent(
            """
            portrait:
              args: 1
            """
        ).strip()
        + "\n"
    )
    ink_file = dialogue_dir / "alice.ink"
    ink_file.write_text('~ portrait("sad")\nHello.\n')

    compiled = ink_json_path("alice.ink", dialogue_dir)
    assert compiled is not None
    assert compiled.exists()


def test_custom_external_function_prints_placeholder(tmp_path: Path) -> None:
    if shutil.which("inklecate") is None:
        pytest.skip("inklecate is not installed")

    world_dir = tmp_path / "world"
    (world_dir / "rooms").mkdir(parents=True)
    (world_dir / "game_objects").mkdir(parents=True)
    (world_dir / "items").mkdir(parents=True)
    (tmp_path / "dialogue").mkdir(parents=True)

    (world_dir / "game.yaml").write_text("player: hero\n", encoding="utf-8")
    (world_dir / "game_objects" / "hero.yaml").write_text(
        "name: Hero\nlocation: start\ninventory: []\n", encoding="utf-8"
    )
    (world_dir / "game_objects" / "alice.yaml").write_text(
        "name: Alice\n", encoding="utf-8"
    )
    (world_dir / "rooms" / "start.yaml").write_text(
        textwrap.dedent(
            """
            name: Start
            exits: []
            items: []
            objects:
              - hero
              - alice
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "dialogue" / "globals.ink").write_text("EXTERNAL get(key)\n")
    (tmp_path / "dialogue" / "custom_externals.yaml").write_text(
        textwrap.dedent(
            """
            portrait:
              args: 1
            """
        ).strip()
        + "\n"
    )
    (tmp_path / "dialogue" / "alice.ink").write_text(
        textwrap.dedent(
            """
            ~ portrait(\"sad\")
            Hello.
            """
        ).strip()
        + "\n"
    )

    world = World(tmp_path)
    world.handle_action("t", "alice")

    context = world.get_context()
    assert context.__class__.__name__ == "Dialogue"
    assert '~ portrait("sad")' in context.last_text
