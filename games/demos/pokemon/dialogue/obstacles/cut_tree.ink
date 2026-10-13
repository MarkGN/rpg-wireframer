{has("$player.inventory", "cut") and has("$player.inventory", "cascade_badge"):
    -> cut
}
It's a tree blocking your path.
-> END

== cut
You cut it down.
~ move("$player", "$current_room", "$npc_room")
-> END