{ get("$self.gifted"):
    -> given
}
Ah! Finally!
You're the first person to reach the secret house!
I was getting worried no-one would win our campaign prize.
~ speaker("$player")
Aren't publicity stunts supposed to involve, I don't know, publicity?
~ speaker("$self")
...
Take this surf HM and get out.
~ add("$player.inventory", "surf")
~ set("$self.given", 1)
-> END

== given
Haven't you humiliated me enough already?
~ speaker("$player")
I guess.
For now.
-> END