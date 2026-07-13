{get("$self.open"):
    It's already opened.
    -> END
  - else:
    ~ set("$self.open", true)
    You find {parse_inventory("$self")}.
    ~ loot()
    -> END
}