
~ badge = "thunder_badge"

{ has("$player.inventory", badge):
    -> post_victory
    else:
    -> challenge}

== challenge
Are you man enough to fight me?
~ scenario("battle")
-> END

== win
~ victory()
Sonic boom!
~ add("$player.inventory", badge)
~ add("$player.inventory", "tm_14")
-> END

== post_victory
Go home and be a family man.
-> END