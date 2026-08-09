{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
Did you see that Mew just now?
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
Wow, you're pretty tough!
-> END

== lose
I wonder who's stronger, Mew or my bugs?
~ defeat()
-> END

== post_victory
I guess I should focus on what really matters, bugs, instead of chasing after things that definitely don't exist.
-> END
