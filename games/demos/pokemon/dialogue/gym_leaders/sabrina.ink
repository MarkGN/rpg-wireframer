{ has("$player.inventory", "marsh_badge"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
I've got a question.
Why does the psychic have the marsh badge and the poison guy the soul badge?
We should swap.
~ scenario("trainer")
-> END

== win
~ victory()
Uck. Now I have neither badge.
~ add("$player.inventory", "marsh_badge")
~ add("$player.inventory", "tm_46")
-> END

== lose
Look on the bright side: you lasted longer than the fighting (snerk) gym.
~ defeat()
-> END

== post_victory
Psychic has a type advantage over poison.
I should just go beat it out of him.
-> END
