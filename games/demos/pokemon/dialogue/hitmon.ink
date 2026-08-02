{ get("karate_master.chose_hitmon"):
    -> fomo
}
Hitmon! Hitmon!
(Take it?)
+ Yes
    ~ set("karate_master.chose_hitmon",1)
    # add $self to party
    -> END
+ No
-> END

== fomo
Hitmon! Hitmon!
You should've chosen me.
-> END