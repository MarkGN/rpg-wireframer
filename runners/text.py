from pathlib import Path
from sys import argv

from .action import render_action
from .contexts.combat import Combat
from .contexts.dialogue import Dialogue
from .contexts.explore import Explore
from .contexts.shop import Shop
from .context_independent_actions import (
    get_context_independent_actions,
    handle_context_independent_action,
)
from .world import World


def main() -> None:
    game_dir = argv[1]
    world = World(Path(f"{game_dir}"))

    while True:
        # get and print context from world
        context = world.get_context()
        if isinstance(context, Combat):
            print("#" * 30)
            print("You are in combat right now!")
            print("#" * 30)
        if isinstance(context, Dialogue):
            print("#" * 30)
            print(
                world.world_state["game_objects"]
                .get(context.npc, None)
                .get("name", None)
            )
            print(context.last_text)
            print("#" * 30)
        if isinstance(context, Explore):
            room = world.display_room()
            print("#" * 30)
            print(room.get("name", f'{room.get("handle")} name not found'))
            print(room.get("description", None))
            print("#" * 30)
        elif isinstance(context, Shop):
            print("#" * 30)
            print(context.line)
            for item in context.inventory:
                print(
                    world.world_state["items"][item]["name"],
                    world.world_state["items"][item]["price"],
                )
            print("#" * 30)
        # get and print actions from world
        actions = context.actions(world)
        context_independent_actions = get_context_independent_actions(world)
        for index, action in enumerate(context_independent_actions):
            print(index, action["label"])
        for i, action in enumerate(actions, len(context_independent_actions)):
            print(i, render_action(world, action))
        # elicit choice
        choice = input("  > ").strip()
        if choice.isdigit():
            choice_index = int(choice)
            if 0 <= choice_index < len(context_independent_actions):
                action_id = context_independent_actions[choice_index]["id"]
                should_exit = handle_context_independent_action(world, action_id)
                if should_exit:
                    return
                continue

            raw = (
                actions[choice_index - len(context_independent_actions)]
                if (0 <= choice_index - len(context_independent_actions) < len(actions))
                else None
            )
            if not raw:
                continue
            # have world apply choice
            print("debug: your action was", raw)
            world.handle_action(raw.interact_type, raw.target)
            if raw.interact_type == "a":
                print(f"  You pick up the {raw.target}.")


if __name__ == "__main__":
    main()
