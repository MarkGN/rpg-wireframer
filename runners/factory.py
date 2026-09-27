from .contexts.craft import Craft
from .contexts.dialogue import Dialogue
from .contexts.encounter import Encounter
from .contexts.explore import Explore
from .contexts.shop import Shop


class ContextFactory:
    def create(self, context, scenario, npc, **kwargs):
        match context:
            case "explore":
                return Explore()
            case "dialogue":
                return Dialogue(npc, **kwargs)
            case "encounter":
                return Encounter(scenario["outcomes"])
            case "shop":
                return Shop(inventory_handle=scenario["stock"]["source"], npc=npc)
            case "craft":
                recipes_file = scenario.get("recipes") if isinstance(scenario, dict) else None
                return Craft(recipes_file=recipes_file)
