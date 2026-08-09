{ has("$player.inventory", "earth_badge"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
You're the kid who messed up my operation!
I'd have you whacked, but as this is G-rated, let's just battle.
~ scenario("trainer")
-> END

== win
~ victory()
By Mafia Law, I hereby name you the new Don.
Serve oppressively and well.
~ add("$player.inventory", "earth_badge")
~ add("$player.inventory", "tm_27")
-> END

== lose
Now beat it, kid.
~ defeat()
-> END

== post_victory
So who do we beat up first? The blacks, the Chinese, or the Jews?
I need to know, time is beatings.
-> END
