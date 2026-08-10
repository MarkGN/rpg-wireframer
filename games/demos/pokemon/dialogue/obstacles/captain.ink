{ get("$self.seasick"):
  -> massage
}
I feel nice. You should do that professionally.
~ speaker("$player")
I need an adult.
~ speaker("$self")
~ emotion("sleazy")
I am an adult.
-> END

== massage
Ugh, I feel awful.
You, small child: give me a massage!
~ speaker("$player")
I see nothing wrong with this.
(You rub his shoulders. Thoroughly. Powerfully. Deeply. Sensuously.)
~ set("$self.seasick", false)
~ speaker("$self")
Ooh yeah, that's nice.
Here, have a tip: HM01, Cut.
~ add("$player.inventory", "cut")
~ speaker("$player")
Why is it sticky?
~ speaker("$self")
No reason.
-> END