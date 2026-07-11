from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world import World
from inkpython import Story
import json
import os
import subprocess
import tempfile
from pathlib import Path
from ..action import Action, InteractType
from ..binder import Binder
from ..context import Context

TALK = "c"


class Dialogue(Context):
    """
    Walking around the world map.
    """

    def __init__(self, npc):
        self.npc: str = npc
        self.last_text: str = ""
        self.story: Story = None

    def on_enter(self, world: World) -> None:
        """
        Begin an NPC's Ink story.

        External functions honoured:
            gain(target, key, amount)
            add(target, item)
            remove(target, item)
            has(target, item)
            get(key)
            set(key, value)
            move(npc, location)
            shop(inventory)
        """
        meta = world.world_state["game_objects"].get(self.npc, {})
        dialogue_dir = Path(world.game_path) / "dialogue"
        json_path = ink_json_path(meta.get("ink", f"{self.npc}") + ".ink", dialogue_dir)
        if json_path is None:
            print(f"(No dialogue available for {meta.get('name', self.npc)}.)\n")
            return

        # --- load compiled story ---
        with open(json_path) as f:
            story_data = json.load(f)

        self.story = Story(story_data)

        def binder(key):
            return Binder({"player": world.player_handle, "self": self.npc}).apply(key)

        # --- register external functions ---

        def ext_get(key):
            return world.get_state(binder(key))

        def ext_set(key, value):
            world.set_state(binder(key), value)

        def ext_increase(key, value):
            terms = binder(key).split(".")
            d = world.world_state
            for term in terms[:-1]:
                d = d[term]
            d[terms[-1]] += value

        def ext_transfer(d, r, value) -> None:
            donor = binder(d)
            recipient = binder(r)
            if isinstance(value, list):
                ext_remove_item(donor, value)
                ext_add_item(recipient, value)
            elif isinstance(value, int):
                ext_increase(donor, -value)
                ext_increase(recipient, value)

        def ext_has_item(key, item) -> int:
            terms = binder(key).split(".")
            value = world.world_state
            for term in terms:
                value = value[term]
            return item in value

        def ext_add_item(key, item):
            world.add_item(binder(key), item)

        def ext_remove_item(key, item):
            terms = binder(key).split(".")
            d = world.world_state
            for term in terms[:-1]:
                d = d[term]
            if item in d[terms[-1]]:
                d[terms[-1]].remove(item)

        def ext_at_npc(npc):
            return npc in world.npcs_in_room()

        def ext_move_npc(npc, location):
            world.world_state["game_objects"][npc]["location"] = [location]

        def ext_scenario(script):
            world.push_scenario(script=script, npc=self.npc)
            return

        self.story.BindExternalFunction("get", ext_get)
        self.story.BindExternalFunction("set", ext_set)
        self.story.BindExternalFunction("increase", ext_increase)
        self.story.BindExternalFunction("transfer", ext_transfer)
        self.story.BindExternalFunction("add", ext_add_item)
        self.story.BindExternalFunction("remove", ext_remove_item)
        self.story.BindExternalFunction("has", ext_has_item)
        self.story.BindExternalFunction("move", ext_move_npc)
        self.story.BindExternalFunction("present", ext_at_npc)
        self.story.BindExternalFunction("scenario", ext_scenario)

        self.step_story()

    def step_story(self):
        parts = []

        while self.story.canContinue:
            text = self.story.Continue()
            if text:
                text = text.strip()
                if text:
                    parts.append(text)

        self.last_text = "\n".join(parts)

    def actions(self, world: World):
        if self.story.canContinue:
            return [Action(InteractType.CONTINUE_TALK, "-continue-")]
        elif self.story.currentChoices:
            return [
                Action(InteractType.CONTINUE_TALK, choice.text)
                for choice in self.story.currentChoices
            ]
        else:
            return [Action(InteractType.END_DIALOGUE)]

    # With dialogues, the verb is always "keep talking"
    def apply(self, verb: str, target: str, world: World):

        self.last_text = ""
        if verb == InteractType.END_DIALOGUE:
            world.pop_context()
        elif self.story.canContinue:
            lines = []
            while self.story.canContinue:
                lines.append(self.story.Continue().strip())
            self.last_text = "\n".join(lines)
        elif self.story.currentChoices:
            ix = [c.text for c in self.story.currentChoices].index(target)
            self.story.ChooseChoiceIndex(ix)
            self.last_text += self.story.Continue().strip()
        else:
            world.pop_context()

    def on_resume(self, world, **kwargs):
        if "goto" in kwargs:
            self.story.ChoosePathString(kwargs.get("goto"))
        self.step_story()


# ---------------------------------------------------------------------------
# Ink integration
# ---------------------------------------------------------------------------


def find_ink_path(ink_filename: str, dialogue_dir: Path) -> Path | None:
    candidate = dialogue_dir / ink_filename
    if candidate.exists():
        return candidate

    target_name = Path(ink_filename).name
    for path in sorted(dialogue_dir.rglob("*.ink")):
        if path.name == target_name:
            return path

    return None


def ink_json_path(ink_filename: str, dialogue_dir: Path) -> Path | None:
    """Return path to compiled .ink.json, compiling with inklecate if needed."""
    ink_path = find_ink_path(ink_filename, dialogue_dir)
    if ink_path is None:
        print(f"[engine] Dialogue file not found: {dialogue_dir / ink_filename}")
        return None

    json_path = ink_path.with_suffix(".ink.json")
    source_path = ink_path
    temp_path = None

    globals_path = dialogue_dir / "globals.ink"
    if globals_path.exists():
        include_path = os.path.relpath(globals_path, start=ink_path.parent)
        temp_file = tempfile.NamedTemporaryFile(
            dir=ink_path.parent,
            suffix=".ink",
            delete=False,
            mode="w",
            encoding="utf-8",
        )
        try:
            temp_file.write(f"INCLUDE {include_path}\n")
            temp_file.write(ink_path.read_text(encoding="utf-8"))
            temp_file.close()
            temp_path = Path(temp_file.name)
            source_path = temp_path

            if (
                not json_path.exists()
                or ink_path.stat().st_mtime > json_path.stat().st_mtime
            ):
                result = subprocess.run(
                    ["inklecate", "-o", str(json_path), str(source_path)],
                    capture_output=True,
                    text=True,
                )
            else:
                result = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    else:
        if (
            not json_path.exists()
            or ink_path.stat().st_mtime > json_path.stat().st_mtime
        ):
            result = subprocess.run(
                ["inklecate", "-o", str(json_path), str(source_path)],
                capture_output=True,
                text=True,
            )
        else:
            result = None

    if result is not None and result.returncode != 0:
        print(f"[debug] inklecate return code: {result.returncode}")
        print(f"[debug] stdout: {result.stdout}")
        print(f"[debug] stderr: {result.stderr}")
        print(f"[debug] json expected at: {json_path}")
        print(f"[debug] json exists: {json_path.exists()}")
        return None

    return json_path
