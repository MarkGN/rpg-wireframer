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
    quests_config: dict[str, dict] | None = None,
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

    quests_dir = world_dir / "quests"
    quests_dir.mkdir(exist_ok=True)

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

    if quests_config:
        for q_id, q_data in quests_config.items():
            (quests_dir / f"{q_id}.yaml").write_text(
                yaml.dump(q_data),
                encoding="utf-8",
            )

    return game_dir


class TestRoomReachabilityValidator:
    """Tests for the STRIPS room reachability validator."""

    def test_quest_goal_room_reachable(self, tmp_path: Path) -> None:
        """Test a quest where goal_room is reachable."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"North": "hall"}},
                "hall": {"exits": {"South": "start", "East": "chamber"}},
                "chamber": {"exits": {"West": "hall"}},
            },
            quests_config={"reach_chamber": {"name": "Reach Chamber", "goal_room": "chamber"}},
        )

        uncompletable = validate_quests(game_dir)
        assert uncompletable == []

        validator = QuestValidator(game_dir)
        assert validator.validate() == []
        assert validator.validate_room_reachability() == []
        assert validate_world(game_dir) == []

    def test_quest_goal_room_unreachable(self, tmp_path: Path) -> None:
        """Test detection of an unreachable goal_room quest."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"North": "hall"}},
                "hall": {"exits": {"South": "start"}},
                "dungeon": {"exits": {}},
            },
            quests_config={"reach_dungeon": {"name": "Reach Dungeon", "goal_room": "dungeon"}},
        )

        with pytest.raises(ValueError, match="Quests not completable: reach_dungeon"):
            validate_quests(game_dir)

    def test_quest_irrelevant_branches_ignored(self, tmp_path: Path) -> None:
        """Test that goal-directed planning succeeds despite many irrelevant branches."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"North": "goal_room", "East": "branch_1", "West": "branch_2"}},
                "goal_room": {"exits": {}},
                "branch_1": {"exits": {"East": "branch_1_sub1", "South": "branch_1_sub2"}},
                "branch_1_sub1": {"exits": {}},
                "branch_1_sub2": {"exits": {}},
                "branch_2": {"exits": {"West": "branch_2_sub1"}},
                "branch_2_sub1": {"exits": {}},
            },
            quests_config={"find_goal": {"name": "Find Goal", "goal_room": "goal_room"}},
        )

        uncompletable = validate_quests(game_dir)
        assert uncompletable == []

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


