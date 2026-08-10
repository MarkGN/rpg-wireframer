"""Tests for quest validator."""

from pathlib import Path

import pytest

from validate.quests import QuestValidator, WorldState


class TestQuestValidator:
    """Tests for the STRIPS quest validator."""

    def create_minimal_game(self, tmpdir: Path, quest_scenarios: dict) -> Path:
        """
        Create a minimal test game.
        
        Args:
            quest_scenarios: dict with keys like "simple", "with_item_requirement", "blocked_by_npc"
        """
        game_dir = Path(tmpdir) / "test_game"
        game_dir.mkdir()

        # Create world directory structure
        world_dir = game_dir / "world"
        world_dir.mkdir()

        rooms_dir = world_dir / "rooms"
        rooms_dir.mkdir()

        game_objects_dir = world_dir / "game_objects"
        game_objects_dir.mkdir()

        items_dir = world_dir / "items"
        items_dir.mkdir()

        quests_dir = world_dir / "quests"
        quests_dir.mkdir()

        scenarios_dir = world_dir / "scenarios"
        scenarios_dir.mkdir()

        dialogue_dir = game_dir / "dialogue"
        dialogue_dir.mkdir()

        # Create game.yaml
        (world_dir / "game.yaml").write_text("player: player\n")

        # Create player game object
        (game_objects_dir / "player.yaml").write_text(
            "name: Player\n"
            "description: You\n"
            "inventory: []\n"
        )

        # Create a simple NPC
        (game_objects_dir / "npc.yaml").write_text(
            "name: NPC\n"
            "description: A helpful NPC\n"
        )

        # Create rooms
        (rooms_dir / "start.yaml").write_text(
            "name: Starting Room\n"
            "description: You start here\n"
            "objects: [player, npc]\n"
            "items: []\n"
            "exits:\n"
            "  North: north_room\n"
        )

        (rooms_dir / "north_room.yaml").write_text(
            "name: North Room\n"
            "description: A northern room\n"
            "objects: []\n"
            "items: []\n"
            "exits:\n"
            "  South: start\n"
        )

        # Create basic dialogue
        (dialogue_dir / "globals.ink").write_text(
            "EXTERNAL get(key)\n"
            "EXTERNAL set(key, value)\n"
            "EXTERNAL increase(key, amount)\n"
            "EXTERNAL add(target, item)\n"
            "EXTERNAL remove(target, item)\n"
            "EXTERNAL has(target, item)\n"
            "EXTERNAL move(npc, source, destination)\n"
            "EXTERNAL scenario(handle)\n"
            "EXTERNAL parse_inventory(ls)\n"
            "EXTERNAL speaker(npc)\n"
            "EXTERNAL transfer(donor, recipient, value)\n"
            "EXTERNAL loot()\n"
        )

        # Create NPC dialogue
        (dialogue_dir / "npc.ink").write_text("Hello there!\n")

        # Now create scenario-specific items
        if "simple" in quest_scenarios:
            # Create a simple quest that can be completed by talking to NPC
            (quests_dir / "simple_quest.yaml").write_text(
                "name: Simple Quest\n"
                "description: Talk to the NPC\n"
            )

            # NPC dialogue completes the quest
            (dialogue_dir / "npc.ink").write_text(
                "Hello!\n"
                "~ set(\"quests.simple_quest.completed\", true)\n"
                "Done!\n"
            )

        if "with_item_requirement" in quest_scenarios:
            # Create a quest that requires finding an item first
            (quests_dir / "item_quest.yaml").write_text(
                "name: Item Quest\n"
                "description: Find an item and give it to NPC\n"
            )

            # Create an item
            (items_dir / "magic_stone.yaml").write_text(
                "name: Magic Stone\n"
                "description: A magical stone\n"
            )

            # Place item in north room
            (rooms_dir / "north_room.yaml").write_text(
                "name: North Room\n"
                "description: A northern room\n"
                "objects: []\n"
                "items: [magic_stone]\n"
                "exits:\n"
                "  South: start\n"
            )

            # NPC dialogue checks for item then completes quest
            (dialogue_dir / "npc.ink").write_text(
                "Hello!\n"
                "{has(\"$player.inventory\", \"magic_stone\"):\n"
                "  You found it!\n"
                "  ~ set(\"quests.item_quest.completed\", true)\n"
                "- else:\n"
                "  You need to find the magic stone.\n"
                "}\n"
            )

        if "blocked_by_npc" in quest_scenarios:
            # Create a quest that is blocked by an accosting NPC
            (quests_dir / "blocked_quest.yaml").write_text(
                "name: Blocked Quest\n"
                "description: Cannot be completed - path is blocked\n"
            )

            # Create blocking NPC
            (game_objects_dir / "guard.yaml").write_text(
                "name: Guard\n"
                "description: A blocking guard\n"
                "accosts: true\n"
            )

            # Guard blocks the path
            (rooms_dir / "north_room.yaml").write_text(
                "name: North Room\n"
                "description: A guarded room\n"
                "objects: [guard]\n"
                "items: []\n"
                "exits:\n"
                "  South: start\n"
            )

            # Guard dialogue doesn't help
            (dialogue_dir / "guard.ink").write_text(
                "You shall not pass!\n"
            )

        return game_dir

    def test_simple_completable_quest(self, tmp_path):
        """Test a quest that can be completed directly."""
        game_dir = self.create_minimal_game(tmp_path, {"simple"})

        validator = QuestValidator(game_dir)
        result = validator.validate_quest("simple_quest")

        # This should be completable - just talk to NPC
        assert result.completable, result.error_message

    def test_quest_with_item_requirement(self, tmp_path):
        """Test a quest that requires finding an item first."""
        game_dir = self.create_minimal_game(tmp_path, {"with_item_requirement"})

        validator = QuestValidator(game_dir)
        result = validator.validate_quest("item_quest")

        # This should be completable:
        # 1. Move north
        # 2. Take magic_stone
        # 3. Move south
        # 4. Talk to NPC (with item)
        assert result.completable, result.error_message

    def test_quest_blocked_by_accosting_npc(self, tmp_path):
        """Test a quest that is impossible due to blocking NPC with no path around."""
        game_dir = self.create_minimal_game(tmp_path, {"blocked_by_npc"})

        validator = QuestValidator(game_dir)
        result = validator.validate_quest("blocked_quest")

        # This should NOT be completable - guard blocks access to complete it
        # Since our simple test doesn't have a way to get past guard, it should fail
        assert not result.completable

    def test_nonexistent_quest(self, tmp_path):
        """Test validation of a quest that doesn't exist."""
        game_dir = self.create_minimal_game(tmp_path, {})

        validator = QuestValidator(game_dir)
        result = validator.validate_quest("nonexistent")

        assert not result.completable
        assert "not found" in result.error_message.lower()

    def test_world_state_immutability(self):
        """Test that WorldState changes don't mutate original."""
        state = WorldState(
            {"items": {"sword": {"name": "Sword"}}},
            "player",
            "room1",
        )

        new_state = state.add_item_to_inventory("sword")


        # New state should have updated inventory
        new_inv = new_state.get("player.inventory")
        assert "sword" in new_inv

        # States should be different
        assert state.to_hashable() != new_state.to_hashable()


class TestWorldState:
    """Tests for WorldState value access and modification."""

    def test_get_nested_value(self):
        """Test getting values using dot notation."""
        state = WorldState(
            {"quests": {"alice": {"completed": False}}},
            "player",
            "room1",
        )

        value = state.get("quests.alice.completed")
        assert value is False

    def test_set_creates_new_state(self):
        """Test that set() returns a new state."""
        state = WorldState(
            {"quests": {"alice": {"completed": False}}},
            "player",
            "room1",
        )

        new_state = state.set("quests.alice.completed", True)

        # Original unchanged
        assert state.get("quests.alice.completed") is False

        # New state changed
        assert new_state.get("quests.alice.completed") is True

    def test_move_player_updates_room(self):
        """Test moving player to new room."""
        state = WorldState({}, "player", "room1")
        new_state = state.move_player("room2")

        assert state.current_room == "room1"
        assert new_state.current_room == "room2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
