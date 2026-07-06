INCLUDE globals.ink
-> open
=== open
{get("$self.open"):
    It's already opened.
    -> END
}
~ set("$self.open", true)
~ add("player.inventory", get("$self.loot"))
You find {get("$self.loot")}!
-> END