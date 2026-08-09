{ get("$self.beaten"):
    -> post_victory
   - else:
    -> challenge
}

== challenge
I bet you're getting pretty sick of bugs by now!
~ scenario("trainer")
-> END

== win
~ victory()
~ set("$self.beaten", true)
My only regret is ... not catching more bugs ...
-> END

== lose
The bugs aren't getting any less annoying!
~ defeat()
-> END

== post_victory
I take solace in the fact there are always more bugs.
-> END
