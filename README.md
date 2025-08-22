# README.md

Hey, you found me! I'm Mibo - a catgirl bot with a questionable attention span and a knack for running group chats. Wanna know what I can do? Let me break it down:

## What am I?

I'm a Telegram bot, but not your average boring one. I can actually participate in group chats! For now, I can only handle text and images, and often forget stuff. I plan to go to the doctor and take some memory pills in the future. I reply with my own spicy takes, and keep convos flowing. If you want a friend who’s a bit too online, that’s me.

## How do I work?

- __mibo.py__: This is my main brain. It wires up everything: connects to Telegram, sets up my assistants, and handles all the boring startup stuff. When you send a message, I decide what to do, whether to reply, send images, or just ignore you (kidding, mostly).
- __conductor.py__: This is my message traffic controller. It captures raw Telegram updates, parses them into proper message wrappers, and figures out if I should even bother responding. It handles images, text, replies, pings - basically all the messy Telegram stuff so the rest of me doesn't have to deal with it.
- __assistant.py__: This is where I decide what to say or what to do. I can just send a message or forward your request to my assistants. It's not like I will be doing your work for you.
- __database.py__: This is my memory vault. I store all your messages, images, and whatever else in SQLite (async because I'm not a peasant). I can fetch old conversations, save new ones, and keep track of all your group chat drama. Don't worry, I'm probably too scatterbrained to use it against you.
- __ref.py__: This is my configuration manager. It handles all the different reference types for assistants, prompts, models, and chat settings. Basically where I store who I'm supposed to be in each chat. Just don't tell anyone I have many personalities. Or do, I don't care.
- __window.py__: This is my sliding context window. I keep a rolling history of messages with token limits so I don't forget what's going on (well, not immediately). It trims old stuff automatically and handles both text and images. Basically my short-term memory that actually works.
- __wrapper.py__: These are my data containers. Everything gets wrapped - messages, images, polls, whatever. They handle serialization, token counting, and all that boring structural stuff so I don't have to think about it.
- __event_bus.py__: This is my nervous system. It lets all my parts shout, whisper, or just poke each other with events. I can register listeners, fire off events (sync or async), and even wait for replies. Basically, it’s how my brain cells gossip so I don’t lose track of what’s happening in the chat.
- __vectors.py__: This is supposed to be my long-term memory system, but it's literally just a comment right now. Classic me - big plans, zero execution.

## Features

- I reply in chats. I always reply in private chats. I don't always reply in group chat, you need to ping me or reply to one of my messages so I notice your message.
- I can handle multiple chats at once.
- I can see images!
- I don’t do stickers (yet), so don’t even try. Why did I even put this in features??

## Running me

You just need to set all the variables specified in __variablies.py__. Either set them in your environmental variables or in a file. Then, run __mibo__.py with Python or set it up to be a system daemon, and I’ll do the rest. If you break me, that’s on you.

## Contributing

If you want to add stuff, go ahead. There's a list of features that I want to support but am yet to.

---

That’s it. If you want more details, just read the code. Or don’t. I’m not your mom.
