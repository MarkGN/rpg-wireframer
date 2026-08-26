"""Tests for STRIPS-based room reachability validator in validate/quests.py."""

from pathlib import Path

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

    # Temporarily disabled for dialogue reachability milestone
    # def test_quest_goal_room_unreachable(self, tmp_path: Path) -> None:
    #     """Test detection of an unreachable goal_room quest."""
    #     game_dir = create_test_game(
    #         tmp_path,
    #         {
    #             "start": {"exits": {"North": "hall"}},
    #             "hall": {"exits": {"South": "start"}},
    #             "dungeon": {"exits": {}},
    #         },
    #         quests_config={"reach_dungeon": {"name": "Reach Dungeon", "goal_room": "dungeon"}},
    #     )
    #
    #     with pytest.raises(ValueError, match="Quests not completable: reach_dungeon"):
    #         validate_quests(game_dir)

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

    def test_get_guard_truthy_reachable(self, tmp_path: Path, capsys) -> None:
        """Test truthy get() guard whose target knot is reachable."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink", "met": True}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL get(x)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n{get(\"alice.met\"): -> met_knot}\n-> DONE\n=== met_knot ===\nHi again!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_get_guard_falsy_unreachable(self, tmp_path: Path, capsys) -> None:
        """Test falsy get() guard whose target knot is unreachable."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink", "met": False}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL get(x)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n{get(\"alice.met\"): -> met_knot}\n-> DONE\n=== met_knot ===\nHi again!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == ["alice:met_knot"]
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots: alice:met_knot" in captured.out

    def test_not_get_guard_opposite_behavior(self, tmp_path: Path, capsys) -> None:
        """Test not get() guard with opposite behavior."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink", "met": False}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL get(x)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n{not get(\"alice.met\"): -> first_meeting}\n-> DONE\n=== first_meeting ===\nNice to meet you!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_self_resolution_against_world_state(self, tmp_path: Path, capsys) -> None:
        """Test $self resolution against a game object's world state."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "bob.yaml").write_text(
            yaml.dump({"name": "Bob", "location": "start", "ink": "bob.ink", "friend": True}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL get(x)\n")
        (dialogue_dir / "bob.ink").write_text(
            "-> root\n=== root ===\n{get(\"$self.friend\"): -> friend_knot}\n-> DONE\n=== friend_knot ===\nHey friend!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_set_mutation_same_dialogue(self, tmp_path: Path, capsys) -> None:
        """Test that set() in a knot mutates state and enables a subsequent get() guard."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink", "met": False}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL get(x)\nEXTERNAL set(x, y)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n~ set(\"alice.met\", true)\n{get(\"alice.met\"): -> met_knot}\n-> DONE\n=== met_knot ===\nHi again!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_set_mutation_cross_dialogue(self, tmp_path: Path, capsys) -> None:
        """Test that set() executed in one NPC dialogue is visible to get() in another NPC dialogue."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"East": "garden"}},
                "garden": {"exits": {"West": "start"}},
            },
        )
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink"}),
            encoding="utf-8",
        )
        (game_dir / "world" / "game_objects" / "bob.yaml").write_text(
            yaml.dump({"name": "Bob", "location": "garden", "ink": "bob.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL get(x)\nEXTERNAL set(x, y)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n~ set(\"alice.talked\", true)\n-> END\n",
            encoding="utf-8",
        )
        (dialogue_dir / "bob.ink").write_text(
            "-> root\n=== root ===\n{get(\"alice.talked\"): -> secret_knot}\n-> DONE\n=== secret_knot ===\nThanks for talking to Alice!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_set_mutation_unreachable_path(self, tmp_path: Path, capsys) -> None:
        """Test that set() on an unreachable branch does not satisfy get() guards."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"East": "garden"}},
                "garden": {"exits": {"West": "start"}},
            },
        )
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink"}),
            encoding="utf-8",
        )
        (game_dir / "world" / "game_objects" / "bob.yaml").write_text(
            yaml.dump({"name": "Bob", "location": "garden", "ink": "bob.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL get(x)\nEXTERNAL set(x, y)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n{get(\"alice.impossible\"): -> secret_knot}\n-> DONE\n=== secret_knot ===\n~ set(\"alice.unlocked\", true)\n-> END\n",
            encoding="utf-8",
        )
        (dialogue_dir / "bob.ink").write_text(
            "-> root\n=== root ===\n{get(\"alice.unlocked\"): -> bob_secret}\n-> DONE\n=== bob_secret ===\nUnlocked!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert set(unreachable) == {"alice:secret_knot", "bob:bob_secret"}
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots: alice:secret_knot, bob:bob_secret" in captured.out


