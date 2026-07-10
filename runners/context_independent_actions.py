from __future__ import annotations

from typing import Any
from .presentation import format_inventory, format_quest_log

_DEFAULT_ACTIONS = ["quit", "inventory", "quest_log"]


def get_context_independent_actions(world: Any) -> list[dict[str, str]]:
    game_settings = getattr(world, "game_settings", {}) or {}
    action_ids = game_settings.get(
        "context_independent_actions",
        _DEFAULT_ACTIONS,
    )

    actions: list[dict[str, str]] = []
    for action_id in action_ids:
        if action_id == "quit":
            actions.append({"id": action_id, "label": "Quit game"})
        elif action_id == "inventory":
            actions.append({"id": action_id, "label": "Check inventory"})
        elif action_id == "quest_log":
            actions.append({"id": action_id, "label": "Check quest log"})
    return actions


def handle_context_independent_action(world: Any, action_id: str) -> bool:
    if action_id == "quit":
        print("Goodbye.")
        return True

    if action_id == "inventory":
        for line in format_inventory(world):
            print(line)
        return False

    if action_id == "quest_log":
        for line in format_quest_log(world):
            print(line)
        return False

    return False
