{has("$player.inventory", "cut") and has("$player.inventory", "cascade_badge"):
    -> cut
}
It's a tree blocking your path.
-> END

== cut
You cut it down.
~ move("$player", "rooms.$current_room", "rooms.$npc_room")
-> END