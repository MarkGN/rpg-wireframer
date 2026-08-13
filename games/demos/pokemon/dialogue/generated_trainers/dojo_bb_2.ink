{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
Machoke has taught me things I never thought possible about choking. Let me show you. ;)
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
(taps out, choking)
-> END

== lose
What's that? Gaaargle? Speak up, sub!
~ defeat()
-> END

== post_victory
Lesson learned the hard way: safewords don't work if you can't breathe.
-> END
