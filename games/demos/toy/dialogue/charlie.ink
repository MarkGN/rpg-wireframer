INCLUDE globals.ink
-> greeting
=== greeting

Hello! Welcome to my smithy. I sell metal goods.
+ Buy -> buy
+ Goodbye -> END

== buy
~ scenario("merchant")
-> greeting