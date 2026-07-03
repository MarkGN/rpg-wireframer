INCLUDE globals.ink
-> greeting
=== greeting

Hello! I like you.
{ not get("dave.has-met-player"):
  ~ temp gift = 100
  ~ set("dave.has-met-player", true)
  Here, have {gift} gold.
  I'll see you around, mate.
  ~ increase("player.money", gift)
  ~ increase("dave.money", -gift)
  -> END
- else:
  How's it going, mate? -> END
}