{has("$player.inventory", "cut"):
    -> cut
}
It's a tree blocking your path.
-> END

== cut
You cut it down.
~ set("$self.location", "")
-> END