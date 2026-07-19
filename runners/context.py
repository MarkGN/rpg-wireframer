from __future__ import annotations
from typing import TYPE_CHECKING

from .action import Action

if TYPE_CHECKING:
    from .world import World


class Context:
    def actions(self, world: World) -> list[Action]:
        return []

    def apply(self, verb: str | None, target: str | None, world: World) -> None:
        pass

    def is_finished(self, world: World) -> bool:
        return False

    def on_enter(self, world: World) -> None:
        pass

    def on_resume(self, world: World, **kwargs) -> None:
        pass
