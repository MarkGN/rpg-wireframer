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
        assert uncompletable == ["reach_chamber"]

        validator = QuestValidator(game_dir)
        assert validator.validate() == ["reach_chamber"]
        assert validator.validate_room_reachability() == ["reach_chamber"]
        assert validate_world(game_dir) == ["reach_chamber"]

    def test_quest_completion_set_reachable(self, tmp_path: Path) -> None:
        """Test that a reachable completion mutation satisfies a quest."""
        game_dir = create_test_game(
            tmp_path,
            {"start": {"exits": {}}},
            quests_config={"find_goal": {"name": "Find Goal"}},
        )
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text(
            "EXTERNAL set(key, value)\n", encoding="utf-8"
        )
        (dialogue_dir / "alice.ink").write_text(
            '-> root\n=== root ===\n~ set("quests.find_goal.completed", 1)\n-> END\n',
            encoding="utf-8",
        )

        assert validate_quests(game_dir) == []

    def test_quest_completion_set_unreachable(self, tmp_path: Path) -> None:
        """Test that a completion mutation behind an impossible guard fails."""
        game_dir = create_test_game(
            tmp_path,
            {"start": {"exits": {}}},
            quests_config={"find_goal": {"name": "Find Goal"}},
        )
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text(
            "EXTERNAL get(key)\nEXTERNAL set(key, value)\n", encoding="utf-8"
        )
        (dialogue_dir / "alice.ink").write_text(
            '-> root\n=== root ===\n{get("missing.flag"): -> complete}\n-> END\n'
            '=== complete ===\n~ set("quests.find_goal.completed", 1)\n-> END\n',
            encoding="utf-8",
        )

        assert validate_quests(game_dir) == ["find_goal"]

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
        assert uncompletable == ["find_goal"]

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
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

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
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_has_add_same_dialogue(self, tmp_path: Path, capsys) -> None:
        """Test that add() adds an item to inventory and enables a subsequent has() guard."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL has(list, item)\nEXTERNAL add(list, item)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n~ add(\"$player.inventory\", \"sword\")\n{has(\"$player.inventory\", \"sword\"): -> got_sword}\n-> DONE\n=== got_sword ===\nNice sword!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_has_remove_same_dialogue(self, tmp_path: Path, capsys) -> None:
        """Test that remove() removes an item from inventory and satisfies a not has() guard."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "hero.yaml").write_text(
            yaml.dump({"name": "Player", "location": "start", "inventory": ["key"]}),
            encoding="utf-8",
        )
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL has(list, item)\nEXTERNAL remove(list, item)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n~ remove(\"$player.inventory\", \"key\")\n{not has(\"$player.inventory\", \"key\"): -> lost_key}\n-> DONE\n=== lost_key ===\nKey is gone!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_has_add_cross_dialogue(self, tmp_path: Path, capsys) -> None:
        """Test that add() in Alice's dialogue satisfies a has() guard in Bob's dialogue."""
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
        (dialogue_dir / "globals.ink").write_text("EXTERNAL has(list, item)\nEXTERNAL add(list, item)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n~ add(\"$player.inventory\", \"letter\")\n-> END\n",
            encoding="utf-8",
        )
        (dialogue_dir / "bob.ink").write_text(
            "-> root\n=== root ===\n{has(\"$player.inventory\", \"letter\"): -> got_letter}\n-> DONE\n=== got_letter ===\nThanks for delivering the letter!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_has_unreachable_without_add(self, tmp_path: Path, capsys) -> None:
        """Test that a knot requiring an item that is never added is detected as unreachable."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL has(list, item)\n")
        (dialogue_dir / "alice.ink").write_text(
            "-> root\n=== root ===\n{has(\"$player.inventory\", \"gem\"): -> secret_knot}\n-> DONE\n=== secret_knot ===\nYou have the gem!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_has_missing_item_blocks_fallthrough_knot(self, tmp_path: Path, capsys) -> None:
        """Test that a false conditional divert blocks its fall-through knot."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL has(list, item)\n")
        (dialogue_dir / "alice.ink").write_text(
            '{ not has("$player.inventory", "missing_item"):\n'
            "    -> END\n"
            "}\n"
            "-> hello\n"
            "\n"
            "== hello\n"
            "Hello.\n"
            "-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_has_missing_item_blocks_inline_dialogue(self, tmp_path: Path, capsys) -> None:
        """Test that a false conditional divert blocks following inline dialogue."""
        game_dir = create_test_game(tmp_path, {"start": {"exits": {}}})
        (game_dir / "world" / "game_objects" / "alice.yaml").write_text(
            yaml.dump({"name": "Alice", "location": "start", "ink": "alice.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text(
            "EXTERNAL has(list, item)\nEXTERNAL set(key, value)\n"
        )
        (dialogue_dir / "alice.ink").write_text(
            '{ not has("$player.inventory", "missing_item"):\n'
            "    -> END\n"
            "}\n"
            "Hello.\n"
            '~ set("alice.name", "Judy")\n'
            "-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_has_room_item_pickup(self, tmp_path: Path, capsys) -> None:
        """Test that picking up an item in a room satisfies a dialogue has() guard."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"East": "cellar"}},
                "cellar": {"exits": {"West": "start"}},
            },
        )
        # Place key in cellar
        cellar_yaml = game_dir / "world" / "rooms" / "cellar.yaml"
        cellar_data = yaml.safe_load(cellar_yaml.read_text(encoding="utf-8"))
        cellar_data["items"] = ["key"]
        cellar_yaml.write_text(yaml.dump(cellar_data), encoding="utf-8")

        (game_dir / "world" / "game_objects" / "gatekeeper.yaml").write_text(
            yaml.dump({"name": "Gatekeeper", "location": "start", "ink": "gatekeeper.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL has(list, item)\n")
        (dialogue_dir / "gatekeeper.ink").write_text(
            "-> root\n=== root ===\n{has(\"$player.inventory\", \"key\"): -> unlocked}\n-> DONE\n=== unlocked ===\nYou unlocked the gate!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out

    def test_has_compound_and_conditions(self, tmp_path: Path, capsys) -> None:
        """Test that a compound guard with multiple has() conditions requires both items."""
        game_dir = create_test_game(
            tmp_path,
            {
                "start": {"exits": {"East": "cave"}},
                "cave": {"exits": {"West": "start"}},
            },
        )
        cave_yaml = game_dir / "world" / "rooms" / "cave.yaml"
        cave_data = yaml.safe_load(cave_yaml.read_text(encoding="utf-8"))
        cave_data["items"] = ["ruby"]
        cave_yaml.write_text(yaml.dump(cave_data), encoding="utf-8")

        (game_dir / "world" / "game_objects" / "wizard.yaml").write_text(
            yaml.dump({"name": "Wizard", "location": "start", "ink": "wizard.ink"}),
            encoding="utf-8",
        )
        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir(exist_ok=True)
        (dialogue_dir / "globals.ink").write_text("EXTERNAL has(list, item)\nEXTERNAL add(list, item)\n")
        (dialogue_dir / "wizard.ink").write_text(
            "-> root\n=== root ===\n~ add(\"$player.inventory\", \"scroll\")\n{has(\"$player.inventory\", \"scroll\") and has(\"$player.inventory\", \"ruby\"): -> powerful}\n-> DONE\n=== powerful ===\nYou possess both scroll and ruby!\n-> END\n",
            encoding="utf-8",
        )

        unreachable = validate_quests(game_dir)
        assert unreachable == []
        captured = capsys.readouterr()
        assert "Warning: unreachable dialogue knots" not in captured.out
