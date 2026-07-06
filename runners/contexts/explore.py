from ..context import Context

GET = "a"
GO = "g"
TALK = "t"


class Explore(Context):
    """
    Walking around the world map.
    """

    def actions(self, world):
        locs = [(GO, location) for location in world.rooms[world.current_room]["exits"]]
        present_npcs = [(npc_data.get("interact_prompt", TALK), npc) for npc in world.npcs_in_room() for npc_data in (world.world_state[npc],) if (npc_data["is_visible"] and npc is not world.player_handle)]
        items = [(GET, item) for item in world.rooms[world.current_room]["items"]]
        options = locs + present_npcs + items
        return options

    def apply(self, verb, target, world):
        if verb == GO:
            # go to location
            exits = world.rooms[world.current_room].get("exits", {})
            if target in exits:
                blocking = world.check_block("exits", target)
                if blocking:
                    world.push_context("dialogue", npc=blocking)
                    return
                world.current_room = exits[target]
                accosting = world.check_accost()
                if accosting:
                    world.push_context("dialogue", npc=accosting)
                    return
            else:
                return ValueError(f"Invalid action: {verb} {target}")
        elif verb == TALK:
            # talk to npc
            world.push_context("dialogue", npc=target)
        elif verb == GET:
            # acquire item
            room_items = world.rooms[world.current_room].get("items", [])
            if target in room_items:
                blocking = world.check_block("items", target)
                if blocking:
                    world.push_context("dialogue", blocking)
                    return
                room_items.remove(target)
                world.world_state["player"].setdefault("inventory", []).append(target)
        else:
            return ValueError(f"Invalid action: {verb} {target}")
