{ has("$player.inventory", "rainbow_badge"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
No boys allowed.
~ scenario("trainer")
-> END

== win
~ victory()
Feminism is dead, and thus, so am I. Have my worldly belongings.
~ add("$player.inventory", "rainbow_badge")
~ add("$player.inventory", "tm_21")
-> END

== lose
Woo! Girl power!
~ defeat()
-> END

== post_victory
Brock's actually kind of cute, you know?
Too bad I'm a lesbian.
-> END
