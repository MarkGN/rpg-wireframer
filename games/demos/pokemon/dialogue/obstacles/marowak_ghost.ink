Get ... out ...
{has("$player.inventory", "silph_scope"):
    -> meet
}
-> END

== meet
You make out the ghost of Marowak.
+ Lay to rest
    -> battle
+ Run away
    -> run

== battle
~ scenario("marowak")
-> END

== win
~ set("$self.accosts", 0)
~ set("$self.visible", 0)
~ move("$player", "rooms.$current_room", "rooms.$npc_room")
-> END

== lose
Do you think it hurts to become a ghost?
Or is it peaceful?
~ defeat()
-> END

== run
So be it.
-> END