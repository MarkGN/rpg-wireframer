{ has("$player.inventory", "cascade_badge"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
You're that jerk who totalled my bicycle!
... Wait, that was just in the anime?
You're still a jerk! And Giovanni says I have to practise my waterboarding, so ...
~ scenario("trainer")
-> END

== win
~ victory()
Shoot. Don't tell the Boss. Here's a badge and TM.
~ add("$player.inventory", "cascade_badge")
~ add("$player.inventory", "tm_11")
-> END

== lose
Gee, {get("$player.name")}, I never realised you were such a wet blanket!
...
Wet blanket?
Get it?
~ defeat()
-> END

== post_victory
You know, for a ten-year-old, Ash was kind of cute ...
Anime again? Oops.
-> END
