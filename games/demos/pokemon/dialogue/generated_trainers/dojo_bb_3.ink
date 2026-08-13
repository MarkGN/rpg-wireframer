{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
Behold the power of doing ONLY leg days!
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
Oh. I guess you need arm days after all.
-> END

== lose
Eat hot primeape foot pics!
~ defeat()
-> END

== post_victory
Or maybe the style would work better if I got a Hitmonlee?
-> END
