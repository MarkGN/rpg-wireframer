INCLUDE globals.ink
-> greeting
=== greeting

Ho there! Your money or your life!
+ Fight and win -> win
+ Fight and lose -> lose
+ Run away -> END

=== win
# portrait: narrator
You defeat Bob.
~ temp his_money = get("bob.money")
{his_money > 0:
    You take his {his_money} gold.
    ~ increase("player.money", his_money)
    ~ set("bob.money", 0)
    ~ move("bob", "")
}
-> END

=== lose
# portrait: narrator
Bob defeats you.
~ temp your_money = get("player.money")
{your_money > 0:
    Bob takes your {your_money} gold.
    ~ increase("bob.money", your_money)
    ~ set("player.money", 0)
  - else:
    # portrait: bob-sad
    You could've just said you had no money!
}
-> END