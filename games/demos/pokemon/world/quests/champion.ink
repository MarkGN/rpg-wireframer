{ has("$player.badges", "boulder_badge"):
  -> boulder
}
{ has("$player.badges", "cascade_badge"):
  -> cascade
}
{ has("$player.badges", "thunder_badge"):
  -> thunder
}
{ has("$player.badges", "rainbow_badge"):
  -> rainbow
}
{ has("$player.badges", "marsh_badge"):
  -> marsh
}
{ has("$player.badges", "soul_badge"):
  -> soul
}
{ has("$player.badges", "soul_badge"):
  -> volcano
}
{ has("$player.badges", "earth_badge"):
  -> earth
}
{ get("$lance.final_defeat"):
  -> elite
  else:
  -> rival
}
-> END
== boulder
The next badge is the BoulderBadge, earned at the Pewter City gym. -> END
== boulder
The next badge is the CascadeBadge, earned at the Cerulean City gym. -> END
== boulder
The next badge is the ThunderBadge, earned at the Vermilion City gym. -> END
== boulder
The next badge is the RainbowBadge, earned at the Celadon City gym. -> END
== boulder
The next badge is the MarshBadge, earned at the Saffron City gym. -> END
== boulder
The next badge is the SoulBadge, earned at the Fuschia City gym. -> END
== boulder
The next badge is the VolcanoBadge, earned at the Cinnabar Island gym. -> END
== boulder
The next badge is the EarthBadge, earned at the Viridian City gym. -> END
== elite
Your final challenge is the Elite Four atop the Indigo Plateau. -> END
== rival
It's time to settle the score with your rival past the Elite Four. -> END