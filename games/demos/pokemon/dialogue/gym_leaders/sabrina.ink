
~ badge = "marsh_badge"

{ has("$player.inventory", badge):
    -> post_victory
    else:
    -> challenge}

== challenge
I've got a question.
Why does the psychic have the marsh badge and the poison guy the soul badge?
We should swap.
~ scenario("battle")
-> END

== win
~ victory()
Uck. Now I have neither badge.
~ add("$player.inventory", badge)
~ add("$player.inventory", "tm_46")
-> END

== post_victory
Psychic has a type advantage over poison.
I should just go beat it out of him.
-> END