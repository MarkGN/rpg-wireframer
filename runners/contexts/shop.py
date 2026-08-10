from __future__ import annotations

from typing import TYPE_CHECKING

from ..action import Action, InteractType
from ..binder import Binder

if TYPE_CHECKING:
    from ..world import World
from ..context import Context

BUY = "b"
QUIT = "q"


class Shop(Context):
    """
    Buying from someone.
    Selling is not included (do you really need that in a wireframe?).
    """

    def __init__(self, inventory_handle, npc):
        self.inventory_handle = inventory_handle
        self.inventory = []
        self.npc = npc
        self.line = "Welcome"
        self.binder = None

    def on_enter(self, world: World):
        self.binder = Binder({"player": world.player_handle, "self": self.npc})
        self.inventory = world.get_state(self.binder.apply(self.inventory_handle))

    def actions(self, world: World):
        quit = [Action(InteractType.QUIT, "Quit")]
        return [Action(InteractType.BUY, item) for item in self.inventory] + quit

    def apply(self, verb, target, world: World):
        if verb in {InteractType.QUIT, QUIT}:
            world.pop_context()
        elif verb in {InteractType.BUY, BUY}:
            money = world.get_state(self.binder.apply("$player.money"))
            price = world.get_state(self.binder.apply("items." + target + ".price"))
            # price = world.world_state["items"][target]["price"]
            if money >= price:
                world.set_state(self.binder.apply("$player.money"), money - price)
                world.add_item(self.binder.apply("$player.inventory"), target)
                self.line = "Thank you for your custom."
            else:
                self.line = "You can't afford it."
        else:
            return ValueError("Bad shopping verb", verb)
