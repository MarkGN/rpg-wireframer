INCLUDE globals.ink

{get("bob.is_hostile"):
  -> challenge
- else:
  -> greeting
}
=== greeting
Hey. Sorry about earlier.
You actually seem like a decent guy.
-> END

=== challenge
~ increase("bob.num_encounters",1)
{get("bob.num_encounters"):
- 1:
Ho there! Your money or your life!
+ Take my money. -> surrender
+ Bring it on. -> fight
- 2:
You again! You won't escape me so easily this time! En garde! 
-> fight
- else:
Jeez. You are actually really fast.
You know what? I've got enough cardio for today. You win. I'm not going to rob you.
~ set("bob.is_hostile", false)
-> END
}

=== surrender
# portrait: bob-happy
Huh. No-one ever says that. Sweet. -> lose

=== fight
~ scenario("duel") 
-> END

=== win
# portrait: narrator
(You defeat Bob.)
~ temp his_money = get("bob.money")
{his_money > 0:
    (You take his {his_money} gold.)
    ~ transfer("bob.money", "$player.money", his_money)
}
~ set("bob.is_hostile", false)
~ set("bob.accosts", 0)
~ move("bob", "red_town")
# portrait: bob-sad
Okay, I give up. You win.
I'll go back to town. -> END


=== lose
~ set("bob.is_hostile", false)
~ temp your_money = get("player.money")
{your_money > 0:
    [Bob takes your {your_money} gold.]
    ~ increase("bob.money", your_money)
    ~ set("player.money", 0)
  - else:
    # portrait: bob-sad
    ... I sat around here for this long and you don't even have any money?! Ugh.
}
~ move("bob", "red_town")
~ set("bob.accosts", 0)
Anyway, I'm going back to town. No hard feelings, yeah? -> END


=== flee
(You escape.) -> END