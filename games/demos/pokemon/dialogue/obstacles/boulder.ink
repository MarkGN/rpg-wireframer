{has("$player.inventory", "strength") and has("$player.inventory", "rainbow_badge"):
    -> push
}
It's a boulder blocking your path.
-> END

== push
You push it out of the way.
~ move("$player", "$self_room")
-> END