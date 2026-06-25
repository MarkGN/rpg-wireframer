INCLUDE globals.ink
-> greeting
=== greeting

Hello! Welcome to my magic shop.
+ Buy -> buy
+ Goodbye -> END

== buy
~ shop("alice.inventory")
-> END