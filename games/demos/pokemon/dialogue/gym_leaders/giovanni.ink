
VAR badge = "earth_badge"

{ has("$player.inventory", badge):
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
~ add("$player.inventory", badge)
~ add("$player.inventory", "tm_27")
-> END

== post_victory
So who do we beat up first? The blacks, the Chinese, or the Jews?
I need to know, time is beatings.
-> END