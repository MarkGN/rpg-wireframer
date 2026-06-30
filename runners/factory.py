from .contexts.combat import Combat
from .contexts.dialogue import Dialogue
from .contexts.explore import Explore
from .contexts.shop import Shop


class ContextFactory:
    def create(self, name, **kwargs):
        match name:
            case "explore":
                return Explore(**kwargs)
            case "dialogue":
                return Dialogue(**kwargs)
            case "combat":
                return Combat(**kwargs)
            case "shop":
                return Shop(**kwargs)
