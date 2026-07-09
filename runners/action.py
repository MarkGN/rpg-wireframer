from __future__ import annotations

from enum import Enum
from typing import Any


class InteractType(str, Enum):
    GO_TO = "go_to"
    TALK = "talk"
    CONTINUE_TALK = "cont_talk"
    TAKE = "take"
    BUY = "buy"
    QUIT = "quit"
    FIGHT = "fight"
    END_DIALOGUE = "end_dialogue"


class Action(tuple[InteractType, Any]):
    def __new__(cls, interact_type: InteractType, target: Any = None):
        return tuple.__new__(cls, (interact_type, target))

    @property
    def interact_type(self) -> InteractType:
        return self[0]

    @property
    def target(self) -> Any:
        return self[1]


def render_action(world: Any, action: Action) -> str:
    interact_type = action.interact_type
    target = action.target

    if interact_type == InteractType.GO_TO:
        room_meta = world.world_state["rooms"].get(target, {})
        prompt = room_meta.get("interact_prompt")
        if prompt:
            return f"{prompt} {room_meta.get('name', target)}"
        return f"Go to {room_meta.get('name', target)}"

    if interact_type == InteractType.TALK:
        if isinstance(target, str):
            object_meta = world.world_state["game_objects"].get(target, {})
            prompt = object_meta.get("interact_prompt", "Talk to")
            name = object_meta.get("name", target)
            return f"{prompt} {name}"
        return str(target)

    if interact_type == InteractType.TAKE:
        return f"Take {target}"

    if interact_type == InteractType.BUY:
        return f"Buy {target}"

    if interact_type == InteractType.QUIT:
        return "Quit"

    if interact_type == InteractType.FIGHT:
        return f"Fight {target}"

    if interact_type == InteractType.END_DIALOGUE:
        return "End dialogue"

    return str(target)
