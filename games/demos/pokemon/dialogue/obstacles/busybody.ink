{ get("$self.passed"):
  -> snippy
}

Badgeless guys aren't allowed through. Go beat Brock first.
{ has("$player.inventory", "boulder_badge"):
  -> passing
}
-> END

== passing
~ speaker("$player")
I have a BoulderBadge.
~speaker("$self")
Oh. Well --
~speaker("$player")
So how about you mind your damn business?
~ set("$self.passed", 0)
~ pass()
-> END

== snippy
Oh, am I suddenly good enough to talk to the great {"$player.name"}?
~ speaker("$player")
No, I misclicked. You're still too annoying.
~ pass()
-> END