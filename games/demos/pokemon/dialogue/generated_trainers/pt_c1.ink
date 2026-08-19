{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
I see dead people.
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
... and you're not one of them.
-> END

== lose
And you're one of them!
~ defeat()
-> END

== post_victory
I like how quiet it is here. Ghosts notwithstanding
-> END
