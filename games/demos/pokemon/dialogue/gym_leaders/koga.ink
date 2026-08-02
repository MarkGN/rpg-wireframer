
VAR badge = "soul_badge"

{ has("$player.inventory", badge):
    -> post_victory
   - else:
    -> challenge
}

== challenge
The true ninja never sleeps.
He just drinks endless coffee.
So much coffee.
So, so much coffee.
~ scenario("trainer")
-> END

== win
~ victory()
zzz
(you go through his pockets and get a badge and TM)
~ add("$player.inventory", badge)
~ add("$player.inventory", "tm_06")
-> END

== post_victory
zzz
(snort)
zzzzz
-> END