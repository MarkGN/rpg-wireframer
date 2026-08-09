{ has("$player.inventory", "thunder_badge"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
Are you man enough to fight me?
~ scenario("trainer")
-> END

== win
~ victory()
Sonic boom!
~ add("$player.inventory", "thunder_badge")
~ add("$player.inventory", "tm_14")
-> END

== lose
Man enough to fight with me, but not man enough to defeat me!
~ defeat()
-> END

== post_victory
Go home and be a family man.
-> END
