{ has("$player.inventory", "fly"):
    -> fly
}
Hi {get("$player.name")}! I hear Team Rocket controls Silph Co.
If you're still worried about money, you should go there and go through their wallets.
-> END

== fly
Hi! I'm {get("$self.name")}. Nice to meet you, {get("$player.name")}.
Do you want the Fly HM?
~ speaker("$player")
Isn't that, like, incredibly valuable? Don't you want money for it?
~ speaker("$self")
You'd think so, but no.
~ speaker("$player")
Okay. Thanks then.
~ add("$player.inventory", "fly")
-> END