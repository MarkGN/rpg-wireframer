INCLUDE globals.ink
-> greeting
=== greeting

Hello! I like you.
{ not get("dave.has_met_player"):
  ~ temp gift = 100
  ~ set("dave.has_met_player", true)
  Here, have {gift} gold.
  ~ increase("player.money", gift)
  ~ increase("dave.money", -gift)
- else:
  How's it going?
}
-> END