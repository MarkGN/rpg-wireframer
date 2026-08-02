{ get("$self.money") == 0:
    -> post_victory
   - else:
    -> challenge
}

== challenge
It's punch time!
~ scenario("trainer")
-> END

== win
~ victory()
I got punched, so now, you may choose a Hitmon.
-> END

== post_victory
{ get("$self.chose_hitmon"):
    -> final
}
Go on, choose your Hitmon.
Pro tip: Hitmonchan kind of sucks. Elemental punches look cool, but its special stat is lame.
-> END

== final
You have your Hitmon. Train him/her/it well.
-> END