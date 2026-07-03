from .contexts.combat import Combat
from .contexts.dialogue import Dialogue
from .contexts.explore import Explore
from .contexts.shop import Shop
from .world import World
from pathlib import Path
from sys import argv

num_universal_actions = 2


def verb_char_to_english(verb):
    lookup = {
        "a": "Take",
        "b": "Buy",
        "c": "",  # chat
        "f": "",  # fight
        "g": "Go to",
        "q": "",  # quit
        "t": "Talk to",
    }
    return lookup.get(verb, ValueError(f"Unknown verb {verb}"))


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
            print(world.world_state.get(context.npc, None).get("name", None))
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
                print(world.items[item]["name"], world.items[item]["price"])
            print("#" * 30)
        # get and print actions from world
        actions = context.actions(world)
        print(0, "Quit game")
        print(1, "Check inventory")
        for i, (verb, target) in enumerate(actions, num_universal_actions):
            print(i, verb_char_to_english(verb), target)
        # elicit choice
        choice = input("  > ").strip()
        if choice == "0":
            print("Goodbye.")
            return
        elif choice == "1":
            print(f'${world.world_state["player"]["money"]}')
            for item in world.world_state["player"]["inventory"]:
                print(item)
            continue
        else:
            raw = (
                actions[int(choice) - 2]
                if (
                    choice.isdigit()
                    and 0 <= int(choice) - num_universal_actions <= len(actions)
                )
                else None
            )
            if not raw:
                continue
            # have world apply choice
            print("debug: your action was", raw)
            world.handle_action(raw[0], raw[1])
            if raw[0] == "a":
                print(f"  You pick up the {raw[1]}.")


if __name__ == "__main__":
    main()
