{has("$player.inventory", "surf") and has("$player.inventory", "soul_badge"):
    -> surf
}
You can't swim because you're 10 and also not very bright.
-> END

== surf
You surf.
~ move("$player", "$self_room")
-> END