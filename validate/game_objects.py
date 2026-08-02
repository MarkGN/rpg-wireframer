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

    resolved_game_objects: dict[str, dict[str, Any]] = {}

    def resolve_game_object(
        object_id: str, lineage: list[str] | None = None
    ) -> dict[str, Any]:
        if object_id in resolved_game_objects:
            return resolved_game_objects[object_id]
        if lineage is None:
            lineage = []
        if object_id in lineage:
            cycle = " -> ".join(lineage + [object_id])
            raise ValueError(f"Game object instance cycle detected: {cycle}")
        if object_id not in object_paths:
            raise ValueError(f"Game object '{object_id}' not found for inheritance.")

        data = load_yaml(object_paths[object_id])
        if "instance" in data:
            parent_id = data["instance"]
            parent = resolve_game_object(parent_id, lineage + [object_id])
            merged: dict[str, Any] = dict(parent)
            merged.update(data)
            merged.pop("instance", None)
            if data.get("abstract", False):
                merged["abstract"] = True
            else:
                merged["abstract"] = False
            data = merged
        else:
            data = dict(data)

        data.setdefault("accosts", False)
        data.setdefault("dialogue", f"{object_id}.ink")
        data.setdefault("inventory", [])
        data.setdefault("is_visible", True)
        data.setdefault("money", 0)

        resolved_game_objects[object_id] = data
        return data

    for object_id in sorted(object_paths):
        raw_data = load_yaml(object_paths[object_id])
        if raw_data.get("abstract", False) and "instance" not in raw_data:
            continue

        data = resolve_game_object(object_id)

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
