{ get("$self.gifted"):
    -> given
}
Oh hey, you rescued me. Neat.
~ speaker("$player")
It's what I do.
~ speaker("$self")
Here, have a Pokeflute as thanks.
~ add("$player.inventory", "poke_flute")
~ set("$self.given", 1)
-> END

== given
How's the flute?
~ speaker("$player")
Loud. The cops keep telling me the HOA wants my head.
-> END