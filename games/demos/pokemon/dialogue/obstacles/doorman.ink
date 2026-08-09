{ not has("$player.inventory", "boulder_badge"):
  -> boulder
}
{ not has("$player.inventory", "cascade_badge"):
  -> cascade
}
{ not has("$player.inventory", "thunder_badge"):
  -> thunder
}
{ not has("$player.inventory", "rainbow_badge"):
  -> rainbow
}
{ not has("$player.inventory", "marsh_badge"):
  -> marsh
}
{ not has("$player.inventory", "soul_badge"):
  -> soul
}
{ not has("$player.inventory", "volcano_badge"):
  -> volcano
}
{ not has("$player.inventory", "earth_badge"):
  -> earth
}
-> pass

== boulder
Kid, I'm not letting you into an endgame biome without any badges. Start at Pewter City.
-> END

== cascade
Kid, every wild Pokemon past this point is stronger than Misty's weakest. Go to Cerulean City and beat her, and we'll talk.
-> END

== thunder
Kid, if you can't beat that musclehead Lieutenant Surge, you can't hack it here. Go to Vermilion City and talk to him.
-> END

== rainbow
Mate, Erika from Celadon City isn't that tough. Not compared to what's past here. If you can't beat her, you can't survive out here.
-> END

== marsh
Mate, if you want to be let through here, you need a MarshBadge. Go to Saffron City and get one.
-> END

== soul
Mate, things out here sneak up on you. Go to Koga of Fuschia City for certification you can handle that.
-> END

== volcano
Six badges. Not bad. But still not enough. Go to Cinnabar Island and get a VolcanoBadge.
-> END

== earth
Seven badges. You still need the EarthBadge from Viridian City. Bring your A-game. That gym leader doesn't play.
-> END

== pass
{ get("$self.passed"):
  Hey, {get("$player.name")}. Good luck out there.
- else:
  Let me see ...
  All eight badges. Everything is in order. You're qualified to pass.
  Well done, sir.
  And good luck.
  ~ set("$self.passed", true)
}
-> END