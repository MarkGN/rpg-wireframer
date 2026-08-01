
~ badge = "cascade_badge"

{ has("$player.inventory", badge):
    -> post_victory
    else:
    -> challenge}

== challenge
You're that jerk who totalled my bicycle!
... Wait, that was just in the anime?
You're still a jerk! And Giovanni says I have to practise my waterboarding, so ...
~ scenario("battle")
-> END

== win
~ victory()
Shoot. Don't tell the Boss. Here's a badge and TM.
~ add("$player.inventory", badge)
~ add("$player.inventory", "tm_11")

~ remove("cerulean_trashed.objects", "cerulean_cop")
-> END

== post_victory
You know, for a ten-year-old, Ash was kind of cute ...
Anime again? Oops.
-> END