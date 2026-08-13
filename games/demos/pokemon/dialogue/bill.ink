Hello, fellow nerd!
{ not has("$player.inventory", "anne_ticket"):
    Here, have a cruise ship ticket.
    ~ add("$player.inventory", "anne_ticket")
    ~ speaker("$player")
    Uh. Thanks? I guess?
    ~ speaker("$self")
    I'm in a wacky mood. Want a Petri dish of ebola virus?
    ~ speaker("$player")
    I do not.
}
-> END