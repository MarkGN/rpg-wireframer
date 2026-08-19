{ get("$self.toothy"):
    -> grin
}
Un udderhucker htole ny gold teet!
When I get ny hand on hin, I'n gonna tear hid lunk outta hid ard!
{ has("$player.inventory", "gold_teeth"):
    -> teeth
}
-> END

== teeth
+ Offer teeth
    What? Dat's ny teet! Gidden to ne!
    (he takes the teeth)
    ~ set("$self.toothy", 1)
    Finally!
    Who'd you get these off?
    ~ speaker("$player")
    They were just on the ground.
    You should probably wash them.
    ~ speaker("$self")
    Ah. Hm. I see.
    Well, I need to thank you somehow. Here, have my old strength HM.
    ~ add("$player.inventory", "strength")
    ~ speaker("$player")
    Do I need to wash this?
    ~ speaker("$self")
    Can't hurt.
    -> END
+ Say nothing
    Udder *hucker*!
    -> END

== grin
Hey there {get("$player.name")}.
You know what rocks? Chewing. Chewing rocks.
~ speaker("$player")
Amen, brother.
-> END