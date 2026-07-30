{ has("$player.inventory", volcano_badge"):
    -> post_victory
    else:
    -> challenge}

== challenge
Wahaha!
Hope you have burn heal!
~ scenario("battle")
-> END

== win
~ victory()
Alas, it was I who needed burn heal. Have a badge and a TM.
~ add("$player.inventory", "volcano_badge")
~ add("$player.inventory", "tm_38")
-> END

== post_victory
Good news: I finally procured burn heal!
-> END