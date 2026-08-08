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
    It remains fat, sacklike, fat, and blocking. -> END

== battle
~ scenario("wild")
-> END

== win
~ remove("$npc_room.objects", "$self")
~ move("$player", "rooms.$current_room", "rooms.$npc_room")
-> END