{has("$player.inventory", "pokeflute"):
    -> battle
}
It's a fat sack of fat blocking your path.
-> END

== battle
Play the Pokeflute?
+ Yes
    It woke up and is enraged. -> battle
+ No
    It remains fat, sacklike, and blocking. -> END

== battle
~ scenario("wild")
-> END

== win
~ remove("$current_room.objects", "$self")
# should remove self from all 3 rooms with this
# use a move?
-> END