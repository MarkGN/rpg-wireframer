INCLUDE globals.ink
-> greeting
=== greeting

Hello! I like you.
{ not get("dave.has_met_player"):
  ~ temp gift = 100
  ~ set("dave.has_met_player", true)
  Here, have {gift} gold.
  I'll see you around, mate.
  ~ transfer("dave.money", "player.money", gift)
  -> END
- else:
  How's it going, mate? -> END
}