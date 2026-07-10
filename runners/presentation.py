from __future__ import annotations

from typing import Any

from .action import Action, render_action


def format_explore_header(world: Any, context: Any) -> list[str]:
    room = world.display_room()
    return [
        "#" * 30,
        room.get("name", f'{room.get("handle")} name not found'),
        room.get("description", None),
        "#" * 30,
    ]


def format_dialogue_header(world: Any, context: Any) -> list[str]:
    return [
        "#" * 30,
        world.world_state["game_objects"].get(context.npc, {}).get("name", None),
        context.last_text,
        "#" * 30,
    ]


def format_combat_header() -> list[str]:
    return ["#" * 30, "You are in combat right now!", "#" * 30]


def format_shop_header(world: Any, context: Any) -> list[str]:
    lines = ["#" * 30, context.line]
    for item in context.inventory:
        lines.append(
            f"{world.world_state['items'][item]['name']} {world.world_state['items'][item]['price']}"
        )
    lines.append("#" * 30)
    return lines


def format_context_independent_actions(
    actions: list[dict[str, str]]
) -> list[tuple[int, str]]:
    return [(index, action["label"]) for index, action in enumerate(actions)]


def format_actions(world: Any, actions: list[Action]) -> list[tuple[int, str]]:
    return [
        (index, render_action(world, action)) for index, action in enumerate(actions)
    ]


def format_quest_log(world: Any) -> list[str]:
    entries = world.get_quest_log_entries()
    if not entries:
        return ["No active quests."]
    lines = []
    for entry in entries:
        status = "complete" if entry["complete"] else "in progress"
        lines.append(f"{entry['name']}: stage {entry['stage']} ({status})")
    return lines


def format_inventory(world: Any) -> list[str]:
    lines = [f"${world.world_state['player']['money']}"]
    lines.extend(world.world_state["player"].get("inventory", []))
    return lines
