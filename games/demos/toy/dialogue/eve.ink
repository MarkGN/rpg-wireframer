-> greeting
=== greeting

Hi! Sorry, but you can't come in here.
~ speaker("dave")
You suck!
~ speaker("eve")
No, you suck!
 -> stonewall
=== stonewall
+ Why not? -> ask
+ Please? -> whine
+ Fine. -> END

=== ask
Because I said so. -> stonewall

=== whine
No. -> stonewall