from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


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
    world_dir = game_path / "world"
    objects_dir = world_dir / "game_objects"
    items_dir = world_dir / "items"
    dialogue_dir = game_path / "dialogue"

    item_handles: set[str] = set()
    object_paths: dict[str, Path] = {}
    for path in sorted(objects_dir.rglob("*.yaml")):
        object_paths[path.stem] = path

    for path in sorted(items_dir.rglob("*.yaml")):
        item_handles.add(path.stem)

    if not object_paths:
        raise ValueError(f"No game objects found in {objects_dir}")

    for object_id, path in object_paths.items():
        data = load_yaml(path)

        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Game object {object_id} must have a non-empty name")

        description = data.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"Game object {object_id} must have a non-empty description"
            )

        location = data.get("location")
        if location is None:
            raise ValueError(f"Game object {object_id} must have a location")
        if isinstance(location, list):
            invalid_locations = [item for item in location if not isinstance(item, str)]
            if invalid_locations:
                raise ValueError(
                    f"Game object {object_id} has invalid location values: {invalid_locations}"
                )
        elif not isinstance(location, str):
            raise ValueError(
                f"Game object {object_id} has invalid location value {location!r}"
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

        ink_reference = data.get("ink", object_id)
        if not isinstance(ink_reference, str):
            raise ValueError(f"Game object {object_id} ink reference must be a string")
        if find_ink_path(ink_reference, dialogue_dir) is None:
            raise ValueError(
                f"Game object {object_id} references missing dialogue file '{ink_reference}.ink'"
            )


if __name__ == "__main__":
    import sys

    validate_game_objects(Path(sys.argv[1]))
