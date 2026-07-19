from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..world import World
from ..action import Action, InteractType
from ..context import Context

FIGHT = "f"


class Combat(Context):
    """
    Fighting someone.

    Note: This must ALWAYS be called from a Dialogue.
    """

    def __init__(self, outcomes):
        self.outcomes = {}
        for out in outcomes:
            self.outcomes.update(out)

    def parse_outcomes(self, outcomes):
        half_parsed_outcomes = outcomes.split(";")
        return [
            (out[0].strip(), out[1].strip())
            for x in half_parsed_outcomes
            for out in (x.split(">"),)
        ]

    def actions(self, world: World) -> list[Action]:
        return [Action(InteractType.FIGHT, key) for key in self.outcomes.keys()]

    # This is why we have to assume this was called from a Dialogue
    def apply(self, verb: str | None, target: str | None, world: World):
        if target is not None:
            world.pop_context(goto=self.outcomes[target])
