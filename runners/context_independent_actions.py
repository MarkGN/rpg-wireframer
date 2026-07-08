from __future__ import annotations

from typing import Any


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
        print(f'${world.world_state["player"]["money"]}')
        for item in world.world_state["player"]["inventory"]:
            print(item)
        return False

    if action_id == "quest_log":
        entries = world.get_quest_log_entries()
        if not entries:
            print("No active quests.")
        else:
            for entry in entries:
                status = "complete" if entry["complete"] else "in progress"
                print(f"{entry['name']}: stage {entry['stage']} ({status})")
        return False

    return False
