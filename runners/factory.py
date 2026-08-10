from .contexts.dialogue import Dialogue
from .contexts.encounter import Encounter
from .contexts.explore import Explore
from .contexts.shop import Shop


class ContextFactory:
    def create(self, context, scenario, npc):
        match context:
            case "explore":
                return Explore()
            case "dialogue":
                return Dialogue(npc)
            case "encounter":
                return Encounter(scenario["outcomes"])
            case "shop":
                return Shop(inventory_handle=scenario["stock"]["source"], npc=npc)
