from .contexts.combat import Combat
from .contexts.dialogue import Dialogue
from .contexts.explore import Explore
from .contexts.shop import Shop


class ContextFactory:
    def create(self, context, scenario, npc):
        match context:
            case "explore":
                return Explore()
            case "dialogue":
                return Dialogue(npc)
            case "combat":
                return Combat(scenario["outcomes"])
            case "shop":
                return Shop(inventory_handle=scenario["stock"]["source"], npc=npc)
