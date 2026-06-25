INCLUDE globals.ink
-> greeting
=== greeting

Hello! Welcome to my weapons shop.
+ Buy -> buy
+ Goodbye -> END

== buy
~ shop("charlie.inventory")
-> END