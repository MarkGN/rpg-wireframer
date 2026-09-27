from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..action import Action, InteractType
from ..context import Context

if TYPE_CHECKING:
    from ..world import World

CRAFT = "craft"
QUIT = "q"


class Craft(Context):
    """Crafting menu for recipes defined in a scenario-selected recipes file."""

    def __init__(self, recipes_file: str | None = None):
        self.recipes_file = recipes_file
        self.recipes: list[dict[str, Any]] = []
        self.line = "What would you like to craft?"

    def _load_recipes(self, world: World) -> None:
        if not self.recipes_file:
            self.recipes = []
            return

        recipes_path = Path(world.game_path) / f"{self.recipes_file}.yaml"
        if not recipes_path.exists():
            self.recipes = []
            return

        data = yaml.safe_load(recipes_path.read_text(encoding="utf-8")) or {}
        self.recipes = data.get("recipes", [])

    def on_enter(self, world: World) -> None:
        self._load_recipes(world)

    def _recipe_is_craftable(self, recipe: dict[str, Any], world: World) -> bool:
        inventory = Counter(world.world_state["objects"][world.player_handle].get("inventory", []))
        required = Counter(recipe.get("input", []))
        return all(inventory[item] >= count for item, count in required.items())

    def _craft_recipe(self, recipe: dict[str, Any], world: World) -> None:
        player_inventory = world.world_state["objects"][world.player_handle].setdefault("inventory", [])
        required = Counter(recipe.get("input", []))
        remaining = Counter(player_inventory)
        for item, count in required.items():
            if remaining[item] < count:
                self.line = "You don't have the required ingredients."
                return
        for item, count in required.items():
            for _ in range(count):
                player_inventory.remove(item)
        for item in recipe.get("output", []):
            player_inventory.append(item)
        self.line = f"Crafted: {', '.join(recipe.get('output', [])) or 'nothing'}"

    def actions(self, world: World):
        quit = [Action(InteractType.QUIT, "Quit")]
        craftable = [
            Action(InteractType.CRAFT, index)
            for index, recipe in enumerate(self.recipes)
            if self._recipe_is_craftable(recipe, world)
        ]
        return craftable + quit

    def apply(self, verb, target, world: World):
        if verb in {InteractType.QUIT, QUIT}:
            world.pop_context()
        elif verb in {InteractType.CRAFT, CRAFT}:
            if not isinstance(target, int) or not 0 <= target < len(self.recipes):
                return ValueError("Bad craft recipe", target)
            recipe = self.recipes[target]
            if not self._recipe_is_craftable(recipe, world):
                self.line = "You don't have the required ingredients."
                return
            self._craft_recipe(recipe, world)
        else:
            return ValueError("Bad crafting verb", verb)
