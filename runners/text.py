from pathlib import Path
from sys import argv

from .contexts.combat import Combat
from .contexts.dialogue import Dialogue
from .contexts.explore import Explore
from .contexts.shop import Shop
from .context_independent_actions import (
    get_context_independent_actions,
    handle_context_independent_action,
)
from .presentation import (
    format_actions,
    format_combat_header,
    format_context_independent_actions,
    format_dialogue_header,
    format_explore_header,
    format_shop_header,
)
from .world import World


def main() -> None:
    game_dir = argv[1]
    world = World(Path(f"{game_dir}"))

    while True:
        # get and print context from world
        context = world.get_context()
        if isinstance(context, Combat):
            for line in format_combat_header():
                print(line)
        if isinstance(context, Dialogue):
            for line in format_dialogue_header(world, context):
                print(line)
        if isinstance(context, Explore):
            for line in format_explore_header(world, context):
                print(line)
        elif isinstance(context, Shop):
            for line in format_shop_header(world, context):
                print(line)
        # get and print actions from world
        actions = context.actions(world)
        context_independent_actions = get_context_independent_actions(world)
        for index, label in format_context_independent_actions(
            context_independent_actions
        ):
            print(index, label)
        for index, label in format_actions(world, actions):
            print(index + len(context_independent_actions), label)
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
