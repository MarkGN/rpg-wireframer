from __future__ import annotations

import pytest
import textwrap
from pathlib import Path

from validate.dialogues import validate_dialogues


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_validate_dialogues_accepts_scenario_outcomes(tmp_path: Path) -> None:
    game_path = tmp_path
    write_file(game_path / "dialogue" / "globals.ink", "EXTERNAL scenario(handle)\n")
    write_file(
        game_path / "dialogue" / "hero.ink",
        "Hello.\n~ scenario(\"duel\")\n-> DONE\n=== win ===\nYou win.\n=== lose ===\nYou lose.\n=== flee ===\nYou flee.\n",
    )
    write_file(
        game_path / "world" / "scenarios" / "duel.yaml",
        "context: encounter\noutcomes:\n  - Win: win\n  - Lose: lose\n  - Flee: flee\n",
    )

    validate_dialogues(game_path)


def test_validate_dialogues_rejects_unreachable_knot(tmp_path: Path) -> None:
    game_path = tmp_path
    write_file(game_path / "dialogue" / "hero.ink", "Hello.\n-> DONE\n=== secret ===\nHidden.\n")

    try:
        validate_dialogues(game_path)
        assert False, "Expected unreachable knot validation failure"
    except ValueError as exc:
        assert "unreachable knots/stitches" in str(exc)
        assert "secret" in str(exc)


def test_validate_dialogues_rejects_missing_divert_target(tmp_path: Path) -> None:
    game_path = tmp_path
    write_file(game_path / "dialogue" / "hero.ink", "Hello.\n-> missing\n")

    with pytest.raises(ValueError) as excinfo:
        validate_dialogues(game_path)
    assert "Error compiling Ink" in str(excinfo.value)
    assert "Divert target not found" in str(excinfo.value)


def test_validate_dialogues_rejects_unsupported_scenario_context(tmp_path: Path) -> None:
    game_path = tmp_path
    write_file(game_path / "dialogue" / "globals.ink", "EXTERNAL scenario(handle)\n")
    write_file(
        game_path / "dialogue" / "hero.ink",
        "Hello.\n~ scenario(\"merchant\")\n-> DONE\n=== win ===\nWin.\n",
    )
    write_file(
        game_path / "world" / "scenarios" / "merchant.yaml",
        "context: unsupported_context\n",
    )

    with pytest.raises(ValueError) as excinfo:
        validate_dialogues(game_path)

    assert "unsupported" in str(excinfo.value).lower()


def test_validate_dialogues_accepts_chest_regression(tmp_path: Path) -> None:
    game_path = tmp_path
    demo_dialogue = Path(__file__).parents[1] / "dialogue" / "chest.ink"
    demo_globals = Path(__file__).parents[1] / "dialogue" / "globals.ink"
    write_file(game_path / "dialogue" / "globals.ink", demo_globals.read_text(encoding="utf-8"))
    write_file(game_path / "dialogue" / "chest.ink", demo_dialogue.read_text(encoding="utf-8"))

    validate_dialogues(game_path)
