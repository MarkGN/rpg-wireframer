INCLUDE globals.ink
-> greeting
=== greeting
Hello!
{has("alice.inventory", "flower"):
    Thanks again for getting me the flower.
    They're really useful in potion-making. -> END
  - else:
    Can you do me a favour?
    -> request
}

=== request
If you can find me a red flower, I'll teach you how to cast fireball.
{has("player.inventory", "flower"):
    Yes, that's the one!
    + Trade -> trade
    + Refuse -> refuse
  - else:
    They grow in the fields outside town. -> END
}

=== trade
#set portrait alice-happy
Thanks so much! (takes flower) Now, as promised ...
~ remove("player.inventory", "flower")
~ add("alice.inventory", "flower")
(teaches fireball)
~ add("player.inventory", "fireball")
Now, let me see this flower ... -> END

=== refuse
# set portrait alice-sad
I guess it's yours to keep if you want. -> END