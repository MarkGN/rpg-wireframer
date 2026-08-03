from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..world import World
from inkpython import Story
import inkpython
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
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
        self.current_speaker = npc
        self.last_text: str = ""
        self.story: Story = None
        self.buffered_text: str | None = None
        self.buffered_speaker: str | None = None
        self.external_texts: list[str] = []

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
            return Binder(
                {
                    "player": world.player_handle,
                    "self": self.npc,
                    "current_room": world.current_room,
                }
            ).apply(key)

        # --- register external functions ---

        def ext_get(key: str):
            return world.get_state(binder(key))

        def ext_set(key: str, value: Any):
            world.set_state(binder(key), value)

        def ext_increase(key: str, value: int):
            terms = binder(key).split(".")
            d = world.world_state
            for term in terms[:-1]:
                d = d[term]
            d[terms[-1]] += value

        def ext_transfer(d: str, r: str, value: int) -> None:
            donor = binder(d)
            recipient = binder(r)
            if isinstance(value, list):
                ext_remove_item(donor, value)
                ext_add_item(recipient, value)
            elif isinstance(value, int):
                ext_increase(donor, -value)
                ext_increase(recipient, value)

        def ext_loot() -> None:
            donor = binder("$self.inventory")
            recipient = binder("$player.inventory")
            world.transfer_all(donor, recipient)

        def ext_has_item(key: str, item: str) -> int:
            terms = binder(key).split(".")
            value = world.world_state
            for term in terms:
                value = value[term]
            return item in value

        def ext_add_item(key: str, item: str):
            world.add_item(binder(key), item)

        def ext_remove_item(key: str, item: str):
            terms = binder(key).split(".")
            d = world.world_state
            for term in terms[:-1]:
                d = d[term]
            if item in d[terms[-1]]:
                d[terms[-1]].remove(item)

        def ext_at_npc(npc: str):
            return npc in world.npcs_in_room()

        def ext_move_npc(npc: str, source_room: str, destination_room: str):
            world.move_object(npc, source_room, destination_room)

        def ext_scenario(script: str):
            world.push_scenario(script=script, npc=self.npc)
            return

        def ext_parse_inventory(obj: str):
            s = binder(obj + ".inventory")
            ls = world.get_state(s)
            if len(ls) == 0:
                return "nothing"
            elif len(ls) == 1:
                return ls[0]
            elif len(ls) == 2:
                return ls[0] + " and " + ls[1]
            else:
                return ", ".join(ls[:-1]) + ", and " + ls[-1]

        def ext_speaker(npc: str) -> None:
            self.current_speaker = npc

        self.story.BindExternalFunction("get", ext_get)
        self.story.BindExternalFunction("set", ext_set)
        self.story.BindExternalFunction("increase", ext_increase)
        self.story.BindExternalFunction("transfer", ext_transfer)
        self.story.BindExternalFunction("loot", ext_loot)
        self.story.BindExternalFunction("add", ext_add_item)
        self.story.BindExternalFunction("remove", ext_remove_item)
        self.story.BindExternalFunction("has", ext_has_item)
        self.story.BindExternalFunction("move", ext_move_npc)
        self.story.BindExternalFunction("present", ext_at_npc)
        self.story.BindExternalFunction("scenario", ext_scenario)
        self.story.BindExternalFunction("parse_inventory", ext_parse_inventory)
        self.story.BindExternalFunction("speaker", ext_speaker)

        custom_externals = load_custom_externals_definitions(dialogue_dir)
        for name, arg_count in custom_externals.items():
            self.story.BindExternalFunction(
                name,
                make_custom_external_function(name, arg_count, self),
            )

        self.step_story()

    def step_story(self):
        try:
            parts = []

            if self.buffered_text is not None:
                self.current_speaker = self.buffered_speaker
                parts.append(self.buffered_text)
                self.buffered_text = None
                self.buffered_speaker = None

            while self.story.canContinue:
                old_speaker = self.current_speaker
                text = self.story.Continue()
                if self.external_texts:
                    parts.extend(self.external_texts)
                    self.external_texts = []
                if text:
                    text = text.strip()
                    if text:
                        if self.current_speaker != old_speaker:
                            if parts:
                                self.buffered_text = text
                                self.buffered_speaker = self.current_speaker
                                self.current_speaker = old_speaker
                                break
                            else:
                                parts.append(text)
                        else:
                            parts.append(text)
                if self.external_texts and not self.story.canContinue:
                    parts.extend(self.external_texts)
                    self.external_texts = []

            self.last_text = "\n".join(parts)
        except inkpython.engine.story_exception.StoryException:
            self.story.Error(f"Ink error at {self.story.state.currentPointer}")

    def actions(self, world: World):
        if self.story.canContinue or self.buffered_text is not None:
            return [Action(InteractType.CONTINUE_TALK, "-continue-")]
        elif self.story.currentChoices:
            return [
                Action(InteractType.CONTINUE_TALK, choice.text)
                for choice in self.story.currentChoices
            ]
        else:
            return [Action(InteractType.END_DIALOGUE)]

    # With dialogues, the verb is always "keep talking"
    def apply(self, verb: str | None, target: str | None, world: World):

        self.last_text = ""
        if verb == InteractType.END_DIALOGUE:
            world.pop_context()
        elif self.buffered_text is not None or self.story.canContinue:
            self.step_story()
        elif self.story.currentChoices:
            ix = [c.text for c in self.story.currentChoices].index(target)
            self.story.ChooseChoiceIndex(ix)
            self.step_story()
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
    custom_externals_path = dialogue_dir / "custom_externals.yaml"
    custom_externals = load_custom_externals_definitions(dialogue_dir)
    compile_needed = not json_path.exists()
    if not compile_needed:
        source_mtime = ink_path.stat().st_mtime
        json_mtime = json_path.stat().st_mtime
        if source_mtime > json_mtime:
            compile_needed = True
        elif globals_path.exists() and globals_path.stat().st_mtime > json_mtime:
            compile_needed = True
        elif (
            custom_externals_path.exists()
            and custom_externals_path.stat().st_mtime > json_mtime
        ):
            compile_needed = True

    if globals_path.exists() or custom_externals:
        include_path = (
            os.path.relpath(globals_path, start=ink_path.parent)
            if globals_path.exists()
            else None
        )
        temp_file = tempfile.NamedTemporaryFile(
            dir=ink_path.parent,
            suffix=".ink",
            delete=False,
            mode="w",
            encoding="utf-8",
        )
        try:
            if include_path is not None:
                temp_file.write(f"INCLUDE {include_path}\n")
            if custom_externals:
                for name, arg_count in custom_externals.items():
                    args = ", ".join(f"arg{i}" for i in range(arg_count))
                    temp_file.write(f"EXTERNAL {name}({args})\n")
            temp_file.write(ink_path.read_text(encoding="utf-8"))
            temp_file.close()
            temp_path = Path(temp_file.name)
            source_path = temp_path

            if compile_needed:
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
        if compile_needed:
            result = subprocess.run(
                ["inklecate", "-o", str(json_path), str(source_path)],
                capture_output=True,
                text=True,
            )
        else:
            result = None

    assert (
        result is None or result.returncode == 0
    ), f"Bad .ink: {ink_filename}, {result.stdout}, {result.stderr}"

    return json_path


def load_custom_externals_definitions(dialogue_dir: Path) -> dict[str, int]:
    custom_path = dialogue_dir / "custom_externals.yaml"
    if not custom_path.exists():
        return {}

    with open(custom_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Expected mapping in {custom_path}, got {type(raw).__name__}")

    custom_externals: dict[str, int] = {}
    for name, spec in raw.items():
        if not isinstance(name, str):
            raise ValueError(f"Invalid custom external name {name!r} in {custom_path}")
        if isinstance(spec, dict) and "args" in spec:
            arg_count = spec["args"]
        elif isinstance(spec, int):
            arg_count = spec
        else:
            print("jing", raw, spec, isinstance(spec, dict), "args" in spec)
            raise ValueError(
                f"Invalid custom external spec for {name!r} in {custom_path}: {spec!r}"
            )
        if not isinstance(arg_count, int) or arg_count < 0:
            raise ValueError(
                f"Invalid arg count for {name!r} in {custom_path}: {arg_count!r}"
            )
        custom_externals[name] = arg_count
    return custom_externals


def make_custom_external_function(name: str, arg_count: int, dialogue: "Dialogue"):
    def ext(*args: Any):
        if len(args) != arg_count:
            raise TypeError(
                f"{name}() takes {arg_count} positional arguments but {len(args)} were given"
            )
        formatted_args: list[str] = []
        for arg in args:
            if isinstance(arg, str):
                formatted_args.append(f'"{arg}"')
            else:
                formatted_args.append(str(arg))
        dialogue.external_texts.append(f"~ {name}({', '.join(formatted_args)})")

    return ext
