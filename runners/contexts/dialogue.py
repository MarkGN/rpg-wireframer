from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world import World
from ..context import Context
from inkpython import Story
import json
from pathlib import Path
import subprocess
from sys import argv

DIALOGUE_DIR: str = "games" / (argv[1] / Path("dialogue"))
NPC_KEYWORDS = {
    "name",
    "description",
    "portrait",
    "location",
    "locations",
    "dialogue",
    "accosts",
    "guards-exits",
    "guards-items",
}
TALK = "c"


class Dialogue(Context):
    """
    Walking around the world map.
    """

    def __init__(self, npc):
        self.npc: str = npc
        self.last_text: str = ""

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
        meta = world.npcs.get(self.npc, {})
        json_path = ink_json_path(meta.get("dialogue", f"{self.npc}.ink"))
        if json_path is None:
            print(f"(No dialogue available for {meta.get('name', self.npc)}.)\n")
            return

        # --- load compiled story ---
        with open(json_path) as f:
            story_data = json.load(f)

        self.story = Story(story_data)

        # --- register external functions ---

        def ext_get(key):
            return world.get_state(key)

        def ext_set(key, value):
            world.set_state(key, value)

        def ext_increase(key, value):
            terms = key.split(".")
            d = world.world_state
            for term in terms[:-1]:
                d = d[term]
            d[terms[-1]] += value

        def ext_has_item(key, item) -> int:
            terms = key.split(".")
            value = world.world_state
            for term in terms:
                value = value[term]
            return item in value

        def ext_add_item(key, item):
            world.add_item(key, item)

        def ext_remove_item(key, item):
            terms = key.split(".")
            d = world.world_state
            for term in terms[:-1]:
                d = d[term]
            if item in d[terms[-1]]:
                d[terms[-1]].remove(item)

        def ext_at_npc(npc):
            return npc in self.npcs_in_room()

        def ext_move_npc(npc, location):
            world.npcs[npc]["locations"] = [location]

        def ext_shop(inventory_handle):
            world.push_context("shop", inventory_handle=inventory_handle)
            return

        def ext_combat(outcomes_string):
            world.push_context("combat", outcomes=outcomes_string)
            return

        self.story.BindExternalFunction("get", ext_get)
        self.story.BindExternalFunction("set", ext_set)
        self.story.BindExternalFunction("increase", ext_increase)
        self.story.BindExternalFunction("add", ext_add_item)
        self.story.BindExternalFunction("remove", ext_remove_item)
        self.story.BindExternalFunction("has", ext_has_item)
        self.story.BindExternalFunction("move", ext_move_npc)
        self.story.BindExternalFunction("present", ext_at_npc)
        self.story.BindExternalFunction("shop", ext_shop)
        self.story.BindExternalFunction("combat", ext_combat)

        self.step_story()

    # def step_story(self) -> None:
    #     text = self.story.Continue().strip()
    #     if not text:
    #         self.step_story()
    #     self.last_text = text
    #     return

    def step_story(self) -> None:
        text = ""

        while self.story.canContinue:
            text = self.story.Continue()
            if text is None:
                return

            text = text.strip()
            if text:
                break

        self.last_text = text

    def actions(self, world: World):
        if self.story.canContinue:
            return [(TALK, "-continue-")]
        elif self.story.currentChoices:
            return [(TALK, choice.text) for choice in self.story.currentChoices]
        else:
            return [(TALK, "end dialogue")]

    # With dialogues, the verb is always "keep talking"
    def apply(self, verb: str, target: str, world: World):

        self.last_text = ""
        if self.story.canContinue:
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


def ink_json_path(ink_filename: str) -> Path | None:
    """Return path to compiled .ink.json, compiling with inklecate if needed."""
    ink_path = DIALOGUE_DIR / ink_filename
    json_path = ink_path.with_suffix(".ink.json")

    if not ink_path.exists():
        print(f"[engine] Dialogue file not found: {ink_path}")
        return None

    # Recompile if source is newer than compiled output.
    if not json_path.exists() or ink_path.stat().st_mtime > json_path.stat().st_mtime:
        result = subprocess.run(
            ["inklecate", "-o", str(json_path), str(ink_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[debug] inklecate return code: {result.returncode}")
            print(f"[debug] stdout: {result.stdout}")
            print(f"[debug] stderr: {result.stderr}")
            print(f"[debug] json expected at: {json_path}")
            print(f"[debug] json exists: {json_path.exists()}")
            return None

    return json_path
