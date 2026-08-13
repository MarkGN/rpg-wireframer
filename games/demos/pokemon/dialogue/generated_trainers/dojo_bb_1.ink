{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
Never underestimate that I have punches!
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
Winners don't lose!
-> END

== lose
Hahahahaha. You fight like a girl. Who is also a baby.
~ defeat()
-> END

== post_victory
Hahaha! Your question makes my shoulders bounce.
-> END
