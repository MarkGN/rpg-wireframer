{ get("quests.anne.completed"):
  -> fomo
}
{ not get("$self.accosts"):
  -> mellow
}

You need a ticket to board this ship.
{ has("$player.inventory", "anne_ticket"):
  -> passing
}
-> END

== fomo
Sorry, the ship's gone.
~ speaker("$player")
When will it return?
~ speaker("$self")
Never. It will never return. It was dynamited.
-> END

== mellow
Hey, {get("$player.name")}. I remember you: go ahead.
-> END

== passing
~ speaker("$player")
I have a ticket.
~ speaker("$self")
So you do. Go ahead.
~ set("$self.accosts", 0)
~ pass()
-> END