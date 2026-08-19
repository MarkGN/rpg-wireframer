{get("$player.name")}.
So, you know my Raticate?
...
He was a fighter.
I'm not going to dishonour that.
I'm not going to dishonour *him*.
Let's do this.
~ scenario("trainer")
-> END

== win
Tch. Doesn't matter.
I'm going to keep fighting.
{get("$player.name")} ...
You'd better not get complacent, because I'm going to be ten times tougher next time.
~ move("$self", "$current_room", "")
# add animation here?
-> END

== lose
Yeah. Raticate would've liked this.
Thanks, {get("$player.name")}. I needed this.
~ defeat()
~ move("$self", "$current_room", "")
-> END