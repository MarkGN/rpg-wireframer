{has("$player.inventory", "pokeflute"):
    -> meet
}
It's a fat sack of fat blocking your path.
-> END

== meet
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

== lose
The last thing you remember is Snorlax rolling onto you.
~ defeat()
-> END

== run
You run away. Snorlax goes back to sleep.
-> END

== catch
You catch Snorlax!
~ remove("$npc_room.objects", "$self")
~ move("$player", "rooms.$current_room", "rooms.$npc_room")
-> END