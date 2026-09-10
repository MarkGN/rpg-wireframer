{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
Would you look at that, my henchmen can't stop a kid.
If you want something done right, you do it yourself.
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
Well played. Here, have the Silph Scope.
~ add("$player.inventory", "silph_scope")
~ speaker("$player")
Thank you, sir.
~ set("$self.visible", 0)
-> END

== lose
Now. Beat it, kid.
~ defeat()
-> END

== post_victory
Hey, what are you still doing here?
-> END
