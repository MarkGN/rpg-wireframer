from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .world import World
    from .context import Context
from .action import Action, render_action


def format_explore_header(world: World, context: Context) -> list[str]:
    room = world.display_room()
    return [
        "#" * 30,
        room.get("name", f'{room.get("handle")} name not found'),
        room.get("description", None),
        "#" * 30,
    ]


def format_dialogue_header(world: World, context: Context) -> list[str]:
    return [
        "#" * 30,
        world.world_state["game_objects"]
        .get(context.current_speaker, {})
        .get("name", None),
        context.last_text,
        "#" * 30,
    ]


def format_combat_header() -> list[str]:
    return ["#" * 30, "You are in combat right now!", "#" * 30]


def format_shop_header(world: World, context: Context) -> list[str]:
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


def format_actions(world: World, actions: list[Action]) -> list[tuple[int, str]]:
    return [
        (index, render_action(world, action)) for index, action in enumerate(actions)
    ]


def format_quest_log(world: World) -> list[str]:
    entries = world.get_quest_log_entries()
    if not entries:
        return ["No active quests."]
    lines = []
    for entry in entries:
        status = "complete" if entry["complete"] else "in progress"
        lines.append(f"{entry['name']}: stage {entry['stage']} ({status})")
    return lines


def format_inventory(world: World) -> list[str]:
    player = world.world_state["game_objects"][world.player_handle]
    lines = [f"${player['money']}"]
    lines.extend(player.get("inventory", []))
    return lines
