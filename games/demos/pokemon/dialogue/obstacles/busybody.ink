{ not get("$self.accosts"):
  -> snippy
}

Badgeless guys aren't allowed through. Go beat Brock first.
{ has("$player.inventory", "boulder_badge"):
  -> pass
}
-> END

== pass
~ speaker("$player")
I have a BoulderBadge.
~speaker("$self")
Oh. Well --
~speaker("$player")
So how about you mind your damn business?
~ set("$self.accosts", 0)
~ move("$player", "rooms.$current_room", "rooms.$npc_room")
-> END

== snippy
Oh, am I suddenly good enough to talk to the great {"$player.name"}?
~ speaker("$player")
No, I misclicked. You're still too annoying.
-> END