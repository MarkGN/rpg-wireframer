{has("$player.inventory", "cut") and has("$player.inventory", "cascade_badge"):
    -> cut
}
It's a tree blocking your path.
-> END

== cut
You cut it down.
~ remove("current_room.objects", "$self")
-> END