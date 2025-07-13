# README.md

Hey, you found me! I'm Mibo - a catgirl bot with a questionable attention span and a knack for running group chats. Wanna know what I can do? Let me break it down:

## What am I?

I'm a Telegram bot, but not your average boring one. I can actually participate in group chats! For now, I can only handle text and images, and often forget stuff. I plan to go to the doctor and take some memory pills in the future. I reply with my own spicy takes, and keep convos flowing. If you want a friend who’s a bit too online, that’s me.

## How do I work?

- __mibo.py__: This is my main brain. It wires up everything: connects to Telegram, sets up my assistants, and handles all the boring startup stuff. When you send a message, I decide what to do, whether to reply, send images, or just ignore you (kidding, mostly).
- __assistant.py__: This is where me and my helpers live. I’m not about to do jobs for you - I have assistants who do that for me. I just pick which one to use based on the chat and what you’re asking for. I also decide if I should reply or just lurk.
- __database.py__: This is my memory. I store all your messages, images, and polls here. I use SQLite (async and sync, because I’m fancy like that). I can fetch old messages, save new ones, and keep track of all your weird group chat moments. I swear I don't want to do anything bad with it. For now, no one cares, so whatever.
- __window.py__: This is my sliding context window. I keep a rolling history of messages so I don’t forget what’s going on (well, not too much). I trim old stuff and can handle both text and images. Basically, I try to keep up.
- __event_bus.py__: This is my nervous system. It lets all my parts shout, whisper, or just poke each other with events. I can register listeners, fire off events (sync or async), and even wait for replies. Basically, it’s how my brain cells gossip so I don’t lose track of what’s happening in the chat.

## Features

- I reply in chats. I always reply in private chats, to pings or replies. I don't always reply in group chats.
- I can handle multiple chats at once.
- I don’t do stickers (yet), so don’t even try. Why did I even put this in features??

## Running me

You’ll need a Telegram bot token, an OpenAI key, and a place to store my database. Set those up, run me with Python, and I’ll do the rest. If you break me, that’s on you.

## Contributing

If you want to add stuff, go ahead. There's a list of features that I want to support but can't. The projects page is ordered by priority.

---

That’s it. If you want more details, just read the code. Or don’t. I’m not your mom.
