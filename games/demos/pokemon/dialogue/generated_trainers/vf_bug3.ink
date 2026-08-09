{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
What do you think of my evolved bugs?
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
You don't think much, apparently.
-> END

== lose
Like they say: evolution's the solution if you wanna win.
~ defeat()
-> END

== post_victory
Maybe they still need more evolution.
-> END
