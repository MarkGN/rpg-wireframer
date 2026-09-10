{get("$player.name")}.
I was wondering when you'd arrive.
Take the "when" there as a compliment.
Well.
I guess there's no more need for words.
Here we go.
~ scenario("trainer")
-> END

== win
...
Good game.
~ set("quests.champion.complete", 1)
-> END

== lose
I was always better, {get("$player.name")}.
~ defeat()
-> END