{ get("$self.given"):
    -> given
}
Hey, {get("$player.name")}.
{ pokedex_count() >= 10:
    Ten Pokemon in your Pokedex. Not bad for a ten-year-old.
    That's serious enough to earn this. Here.
    ~ add("$player.inventory", "flash")
    ~ set("$self.given", 1)
    ~ speaker("$player")
    I need an adult.
    ~ speaker("$self")
    You and me both, {get("$player.name")}.
    Catch you around. I have grant paperwork to fill out.
    -> END
  - else:
    If you catch ten Pokemon, I have a present for you.
    The one Professor Oak gave you is one. Just nine more.
    -> END    
}
-> END

== given
How goes the hunt for more Pokemon?
-> END