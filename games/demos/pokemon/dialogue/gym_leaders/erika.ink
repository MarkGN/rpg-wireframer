
VAR badge = "rainbow_badge"

{ has("$player.inventory", badge):
    -> post_victory
   - else:
    -> challenge
}

== challenge
Only girls allowed.
~ scenario("trainer")
-> END

== win
~ victory()
Feminism is dead, and thus, so am I. Have my worldly belongings.
~ add("$player.inventory", badge)
~ add("$player.inventory", "tm_21")
-> END

== post_victory
Brock's actually kind of cute, you know?
Too bad I'm a lesbian.
-> END