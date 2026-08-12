from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from runners import world


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def find_ink_path(ink_filename: str, dialogue_dir: Path) -> Path | None:
    if not ink_filename.endswith(".ink"):
        ink_filename = f"{ink_filename}.ink"
    target_name = Path(ink_filename).name
    for path in sorted(dialogue_dir.rglob("*.ink")):
        if path.name == target_name:
            return path
    return None


def validate_game_objects(game_path: Path | str) -> None:
    game_path = Path(game_path)
    w = world.World(game_path)
    dialogue_dir = game_path / "dialogue"

    item_handles = set(w.world_state["items"].keys())
    game_objects = w.world_state["game_objects"]

    if not game_objects:
        raise ValueError(f"No game objects found in {w.game_objects_dir}")

    for object_id, data in sorted(game_objects.items()):
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Game object {object_id} must have a non-empty name")

        description = data.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"Game object {object_id} must have a non-empty description"
            )

        inventory = data.get("inventory")
        if inventory is not None:
            if not isinstance(inventory, list):
                raise ValueError(f"Game object {object_id} inventory must be a list")
            invalid_items = [item for item in inventory if not isinstance(item, str)]
            if invalid_items:
                raise ValueError(
                    f"Game object {object_id} has invalid inventory items: {invalid_items}"
                )
            missing_items = [item for item in inventory if item not in item_handles]
            if missing_items:
                raise ValueError(
                    f"Game object {object_id} references missing inventory items: {missing_items}"
                )

        ink_reference = data.get("ink", data.get("dialogue", f"{object_id}.ink"))
        if isinstance(ink_reference, str) and ink_reference.endswith(".ink"):
            ink_reference = ink_reference[:-4]
        if not isinstance(ink_reference, str):
            raise TypeError(f"Game object {object_id} ink reference must be a string")
        if find_ink_path(ink_reference, dialogue_dir) is None:
            raise ValueError(
                f"Game object {object_id} references missing dialogue file '{ink_reference}.ink'"
            )


if __name__ == "__main__":
    import sys

    validate_game_objects(Path(sys.argv[1]))
