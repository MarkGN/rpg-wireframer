{ has("$player.inventory", "map"):
    -> met
    else:
    -> new}

== met
Stop screwing around and go eff up my brother.
-> END

== new
Hey, you're trying to mess with my bratty little brother, right?
Here, have his-- have this map.
~ add("$player.inventory", "map")
-> END