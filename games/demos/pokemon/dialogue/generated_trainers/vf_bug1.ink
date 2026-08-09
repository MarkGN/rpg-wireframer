{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
What fool dares challenge the might of the unevolved bug pokemon?!
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
Huh. These are actually kind of underwhelming.
-> END

== lose
Bwahaha! Get bugged!
~ defeat()
-> END

== post_victory
I have such a dumb shtick.
-> END
