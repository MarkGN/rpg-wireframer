from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world import World
from ..context import Context

FIGHT = "f"


class Combat(Context):
    """
    Fighting someone.

    Note: This must ALWAYS be called from a Dialogue.
    """

    def __init__(self, outcomes):
        self.outcomes = self.parse_outcomes(outcomes)

    def parse_outcomes(self, outcomes):
        half_parsed_outcomes = outcomes.split(";")
        return [
            (out[0].strip(), out[1].strip())
            for x in half_parsed_outcomes
            for out in (x.split(">"),)
        ]

    def actions(self, world: World):
        return [(FIGHT, key) for (key, _) in self.outcomes]

    # This is why we have to assume this was called from a Dialogue
    def apply(self, _, target, world: World):
        world.pop_context(goto=dict(self.outcomes)[target])
