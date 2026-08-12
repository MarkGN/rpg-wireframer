"""Tests for STRIPS-based room reachability validator in validate/quests.py."""

from pathlib import Path

import pytest
import yaml

from validate.quests import QuestValidator, validate_quests, validate_world


def create_test_game(
    tmp_path: Path,
    rooms_config: dict[str, dict],
    start_room: str = "start",
    player_handle: str = "hero",
) -> Path:
    """Helper to construct a test game directory structure."""
    game_dir = tmp_path / "test_game"
    game_dir.mkdir(exist_ok=True)

    world_dir = game_dir / "world"
    world_dir.mkdir(exist_ok=True)

    rooms_dir = world_dir / "rooms"
    rooms_dir.mkdir(exist_ok=True)

    game_objects_dir = world_dir / "game_objects"
    game_objects_dir.mkdir(exist_ok=True)

    (world_dir / "game.yaml").write_text(
        yaml.dump({"player": player_handle}), encoding="utf-8"
    )

    (game_objects_dir / f"{player_handle}.yaml").write_text(
        yaml.dump({"name": "Player", "location": start_room}),
        encoding="utf-8",
    )

    for room_id, config in rooms_config.items():
        room_data = {
            "name": room_id.replace("_", " ").title(),
            "exits": config.get("exits", {}),
        }
        (rooms_dir / f"{room_id}.yaml").write_text(
            yaml.dump(room_data),
            encoding="utf-8",
        )

    return game_dir


class TestRoomReachabilityValidator:
    """Tests for the STRIPS room reachability validator."""

    def test_all_rooms_reachable(self, tmp_path: Path) -> None:
        """Test a game layout where all rooms are reachable."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"North": "hall"}},
                "hall": {"exits": {"South": "start", "East": "chamber"}},
                "chamber": {"exits": {"West": "hall"}},
            },
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []

        validator = QuestValidator(game_dir)
        assert validator.validate() == []
        assert validator.validate_room_reachability() == []
        assert validate_world(game_dir) == []

    def test_unreachable_room_detected(self, tmp_path: Path, capsys) -> None:
        """Test detection of an unreachable room."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"North": "hall"}},
                "hall": {"exits": {"South": "start"}},
                "dungeon": {"exits": {}},
            },
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == ["dungeon"]

        captured = capsys.readouterr()
        assert "Warning: unreachable rooms: dungeon" in captured.out

    def test_multiple_unreachable_rooms_sorted(self, tmp_path: Path) -> None:
        """Test that multiple unreachable rooms are returned sorted."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"North": "room_a"}},
                "room_a": {"exits": {}},
                "secret_vault": {"exits": {}},
                "attic": {"exits": {}},
            },
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == ["attic", "secret_vault"]

    def test_one_way_reachability(self, tmp_path: Path) -> None:
        """Test reachability through one-way exits."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"Down": "pit"}},
                "pit": {"exits": {"East": "cave"}},
                "cave": {"exits": {}},
            },
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []

    def test_cycle_and_branching(self, tmp_path: Path) -> None:
        """Test room layouts with cycles and branching."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"North": "node_a", "East": "node_b"}},
                "node_a": {"exits": {"South": "start", "East": "node_c"}},
                "node_b": {"exits": {"West": "start"}},
                "node_c": {"exits": {"West": "node_a"}},
                "isolated_island": {"exits": {"North": "isolated_tower"}},
                "isolated_tower": {"exits": {"South": "isolated_island"}},
            },
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == ["isolated_island", "isolated_tower"]

    def test_invalid_game_file(self, tmp_path: Path) -> None:
        """Test missing player handle raises error."""
        game_dir = tmp_path / "bad_game"
        world_dir = game_dir / "world"
        world_dir.mkdir(parents=True)
        (world_dir / "rooms").mkdir()
        (world_dir / "game_objects").mkdir()
        (world_dir / "rooms" / "start.yaml").write_text("name: Start\n")
        (world_dir / "game.yaml").write_text("{}\n")

        with pytest.raises(ValueError, match="No player defined"):
            validate_quests(game_dir)
