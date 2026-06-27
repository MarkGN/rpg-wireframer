from engine import World

def verb_char_to_english(verb):
    lookup = {"a": "Take",
              "c": "",
              "g": "Go to",
              "t": "Talk to"
              }
    return lookup.get(verb, ValueError(f"Unknown verb {verb}"))

def main() -> None:
    world = World()

    while True:
        # get and print context from world
        if world.last_story_text:
            print("#"*30)
            print(world.npcs.get(world.dialogue_partner,None).get("name", None))
            print(world.last_story_text)
            print("#"*30)
        else:
            room = world.display_room()
            print("#"*30)
            print(room.get("name", f'{room.get("handle")} name not found'))
            print(room.get("description", None))
            print("#"*30)
        # get and print actions from world
        actions = world.get_actions()
        print (0, "Quit game")
        print (1, "Check inventory")
        for (i, (verb, target)) in enumerate(actions, 2):
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
            raw = actions[int(choice)-2] if (choice.isdigit() and 2 <= int(choice) <= len(actions)+2) else None
            if not raw:
                continue
            # have $world apply choice
            world.handle_action(raw[0], raw[1])

if __name__ == "__main__":
    main()