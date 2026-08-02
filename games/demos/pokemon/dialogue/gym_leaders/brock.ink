VAR badge = "boulder_badge"

{ has("$player.inventory", badge):
    -> post_victory
    - else:
    -> challenge
}

== challenge
Hey. Let's rock!
~ scenario("trainer")
-> END

== win
~ victory()
I was too stoned to win. Have a badge and a TM.
~ add("$player.inventory", badge)
~ add("$player.inventory", "tm_34")
-> END

== post_victory
Maybe I should take up breeding instead?
-> END