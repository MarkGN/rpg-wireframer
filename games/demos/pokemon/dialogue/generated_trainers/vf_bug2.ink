{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
Getting poisoned stinks.
To wit:
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
Hmm. So much for that theory.
-> END

== lose
See? Poison is busted!
~ defeat()
-> END

== post_victory
Or maybe what I need is just more poison?
-> END
