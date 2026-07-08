# User

Wireframer is intended to be used by writers who can learn some limited markup but who aren't expected to do any programming. They can write YAML for game object specification and Ink for dialogue, and Wireframer should be able to interpret these as a playable system, allowing the writer to play it directly or run automated verification of correctness. As a stretch goal, there will be a visual runner akin to a visual novel that can use graphical, VA, and music assets, allowing the writer to see how it comes together.

For purposes of development, we use games/demos/toy as the case study.

## Ink

Wireframer uses Ink files for dialogue. There are certain conventions for ease of use.

* All files should begin with `INCLUDE globals.ink`. This file contains standard functions to interface with the engine. You might not need them for a sufficiently basic script, eg a guard who says "Welcome to Corneria!", but it's good practice to include it for all.

* Variables can be called in a Javascript style with `.` delimiter between nested fields, eg `get(quests.alice_flower_stage).

* $self expands to the calling game object. This can be used with "library" Ink files, eg chest.ink can be used by multiple chest objects because it refers to $self.loot rather than chest.loot.

## YAML

Wireframer uses YAML extensively. The objective is that a writer should be able to describe game objects in pure YAML, together with Ink for dialogue. There are certain conventions for ease of use.

# Engine

Wireframer is technically a valid text-only game engine. It's not intended to be fun to play with, it's intended for scenario development: the writer can write his scenario, confirm that it behaves as he intends, then he can hand off a detailed specification to the artist, level builder, and programmer. It should also enable tight iteration and even drastic change of direction, eg if you design a scenario intending a JRPG but decide to try a 3D real-time engine instead.

## Contexts

The game model uses a stack of contexts. A Context can be Explore, Dialogue, Combat, Shop, or in future others such as cutscenes and minigames. The world begins in Explore mode and it's impossible to remove this from the stack. A Context exposes a list of valid actions and can handle each of these actions, eg while exploring, actions might be moving to another area, talking to an NPC, or picking up an item. If we talk to an NPC, that pushes a Dialogue context onto the stack. If the NPC runs a shop, that further pushes a Shop context. When we stop shopping, that Context deletes itself; when we stop talking to him, that one deletes itself too.

Each Context presents its own actions. Others are available regardless of context, eg check inventory, quest log, or quit.

## Text

The text runner is a presentation layer the player can use to run an interactive act-inspect loop.

## World

Much of the game's state is stored in `world.world_state`. Within this, `game_objects` includes NPCs along with things like chests; `global` contains global variables (not often super useful because most variables naturally are attached to some game object, but there are counterexamples); `items` describes items (if you're very lazy, you can create items that aren't defined here, but they'll only have a name, no other data, and it's probably not future-compatible); `rooms` includes rooms; `quests` includes quests.