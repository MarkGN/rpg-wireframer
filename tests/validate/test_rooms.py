"""Tests for room validation in validate/rooms.py."""

from pathlib import Path

import pytest
import yaml

from validate.rooms import validate_world


def _create_game(
    tmp_path: Path,
    room_files: dict[str, dict],
    player_handle: str = "hero",
    start_room: str = "start",
) -> Path:
    """Build a minimal game directory with rooms at the given relative paths.

    room_files maps relative paths (e.g. "town/house.yaml") to room data dicts.
    """
    game_dir = tmp_path / "game"
    world_dir = game_dir / "world"
    rooms_dir = world_dir / "rooms"
    objects_dir = world_dir / "game_objects"

    rooms_dir.mkdir(parents=True)
    objects_dir.mkdir(parents=True)

    (world_dir / "game.yaml").write_text(
        yaml.dump({"player": player_handle}), encoding="utf-8"
    )
    (objects_dir / f"{player_handle}.yaml").write_text(
        yaml.dump({"name": "Player", "location": start_room}), encoding="utf-8"
    )

    for rel_path, data in room_files.items():
        full_path = rooms_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(yaml.dump(data), encoding="utf-8")

    return game_dir


class TestDuplicateRoomNames:
    """Duplicate room name detection across subdirectories."""

    def test_duplicate_room_name_raises(self, tmp_path: Path) -> None:
        """Two rooms with the same stem in different subdirs should error."""
        game_dir = _create_game(
            tmp_path,
            {
                "town/house.yaml": {
                    "name": "Town House",
                    "exits": {"East": "start"},
                },
                "city/house.yaml": {
                    "name": "City House",
                    "exits": {"West": "start"},
                },
                "start.yaml": {
                    "name": "Start",
                    "exits": {"West": "house"},
                },
            },
        )

        with pytest.raises(ValueError, match="Duplicate room name 'house'"):
            validate_world(game_dir)

    def test_unique_room_names_ok(self, tmp_path: Path) -> None:
        """Rooms in subdirs with distinct stems should pass."""
        game_dir = _create_game(
            tmp_path,
            {
                "town/town_house.yaml": {
                    "name": "Town House",
                    "exits": {"East": "start"},
                },
                "city/city_house.yaml": {
                    "name": "City House",
                    "exits": {"West": "start"},
                },
                "start.yaml": {
                    "name": "Start",
                    "exits": {
                        "West": "town_house",
                        "East": "city_house",
                    },
                },
            },
        )

        # Should not raise
        validate_world(game_dir)
