{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
You know what's better than a mankey and a primeape? TWO mankeys and a primeape!
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
I really thought the second mankey would sell this one
-> END

== lose
Heh, knew it. Second mankey always comes in clutch.
~ defeat()
-> END

== post_victory
Maybe what I need is THREE mankeys? Plus primeape. Obviously.
-> END
