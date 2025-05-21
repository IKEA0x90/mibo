import asyncio
import sys
import signal
import openai
import logging

import datetime as dt
from typing import List, Dict
from telegram import Update, Chat, ChatMember, InputFile
from telegram.ext import Application, CallbackContext, CommandHandler, MessageHandler, ChatMemberHandler, filters

from events import event_bus, mibo_events, system_events, assistant_events
from core import assistant, database, conductor, wrapper
from services import tools

class Mibo:
    def __init__(self, token: str, db_path: str = 'env'):
        self.token = token
        self.start_datetime = dt.datetime.now(dt.timezone.utc).timestamp()

        self.bus = event_bus.EventBus()
        self.db = database.Database(self.bus, db_path)
        self.conductor = conductor.Conductor(self.bus)

        self.key = tools.Tool.OPENAI_KEY
        
        self.client = None
        self.assistants = {} 
        self.app = None

        self._prepare(token)

    def _prepare(self, token: str):
        '''
        Prepare the bot by loading the database, getting the openai client, and setting up signal handlers.
        '''
        self.db.initialize_sync()

        self.client = openai.AsyncOpenAI(api_key=self.key)
        temporary_client = openai.OpenAI(api_key=self.key)

        template_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.MIBO_ID)
        cat_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.CAT_ASSISTANT_ID)
        image_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.IMAGE_ASSISTANT_ID)
        poll_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.POLL_ASSISTANT_ID)
        property_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.PROPERTY_ASSISTANT_ID)
        memory_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.MEMORY_ASSISTANT_ID)

        self.templates = {'template': template_assistant,
                    'cat_template': cat_assistant, 
                    'image_template': image_assistant, 
                    'poll_template': poll_assistant, 
                    'property_template': property_assistant, 
                    'memory_template': memory_assistant}

        self.assistants = assistant.initialize_assistants(self.db, self.client, self.bus, self.templates, self.start_datetime)
        
        # Register event listeners
        self.bus.register(assistant_events.AssistantResponse, self._parse_message)
        self.bus.register(mibo_events.MiboMessageResponse, self._send_message)
        self.bus.register(mibo_events.MiboPollResponse, self._create_poll)

        self.app = Application.builder().token(self.token).build()

        # Create stop event for graceful shutdown
        self.stop_event = asyncio.Event()

        self._register_handlers()
        self._system_signals()

    async def run(self):
        '''
        Start the bot
        '''
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        try:
            await self.stop_event.wait()
        finally:
            # kill Mibo (oh no!)
            await self._shutdown(None)

    def _register_handlers(self):
        '''
        Register telegram handlers for commands and messages.
        '''
        self.app.add_handler(CommandHandler('debug', self._debug))
        self.app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), self._handle_message))
        self.app.add_handler(ChatMemberHandler(self._welcome, ChatMemberHandler.MY_CHAT_MEMBER))

    def _system_signals(self):
        '''
        Register system signals to stop the bot gracefully.
        '''
        def _on_signal(sig: signal.Signals, *_):
            self.stop_event.set()
            self.bus.emit_sync(system_events.ShutdownEvent(sig=sig))

        if sys.platform == "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, _on_signal)
        else:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _on_signal, sig)
        
    async def _shutdown(self, polling_task: asyncio.Task):
        print('Shutting down...')

        await self.app.updater.stop() 
        await self.app.stop()
        await self.app.shutdown()
        await self.bus.close()
        await self.db.close()

        print('Shutdown complete.')

    async def _handle_message(self, update: Update, context: CallbackContext):
        '''
        Handles direct and group messages to the bot,
        messages mentioning to the bot in group chats - @itsmiibot,
        messages that are replies to the bot (set ping to True and reply_to to the original message),
        and messages that ping the bot and that are replies to other messages. 

        This just sends the message to the bus.
        The message is processed by the conductor, 
        which creates a MessageWrapper and sends it to the rest of services.
        '''
        if update.effective_message.from_user.id == self.app.bot.id:
            return
        
        event = await self.bus.emit(mibo_events.MiboMessage(update, start_datetime=self.start_datetime))

    async def _system_message(self, chat_id, system_message):
        '''
        Forces the bot to send a message to a chat, possibly appending a system message to the prompt.
        '''
        event = await self.bus.emit(mibo_events.MiboSystemMessage(chat_id, system_message, start_datetime=self.start_datetime))

    async def _parse_message(self, event: assistant_events.AssistantResponse):
        '''
        Parses a message and calls the correct responder.
        '''
        chat_id = event.chat_id
        message: wrapper.MessageWrapper = event.message

        message_text: str = message.message
        message_images: List[wrapper.ImageWrapper] = message.get_images()
        message_sticker: wrapper.StickerWrapper = message.get_sticker()
        message_poll: wrapper.PollWrapper = message.get_poll()

        if message_text or message_images:
            response = mibo_events.MiboMessageResponse(chat_id, message_text, message_images)
            self.bus.emit(response)

        if message_sticker:
            response = system_events.ChatErrorEvent(chat_id, 'Stickers are not supported yet.')
            self.bus.emit(response)

        if message_poll:
            response = mibo_events.MiboPollResponse(chat_id, message_poll)
            self.bus.emit(response)    
        
    async def _send_message(self, event: mibo_events.MiboMessageResponse) -> None:
        '''
        Send the text and images from the response message.
        Text and/or images may be empty - in that case, only the non-empty item is sent.
        If both are empty, nothing is sent.
        If images are sent, they are combined into an album and the message is sent appended to the first image (like users do).
        '''
        chat_id: str = event.chat_id
        text: str = event.text
        images: List[wrapper.ImageWrapper] = event.images

        if not text and not images:
            return

        # If only text
        if text and not images:
            await self.app.bot.send_message(chat_id=chat_id, text=text)
            return

        # If only images
        if images and not text:
            media_group = [
                self.app.bot._wrap_input_media_photo(image.image_url) for image in images
            ]
            await self.app.bot.send_media_group(chat_id=chat_id, media=media_group)
            return

        # If both text and images: send as album, text as caption to first image
        if images and text:
            from telegram import InputMediaPhoto
            media_group = []
            for idx, image in enumerate(images):
                caption = text if idx == 0 else None
                media_group.append(InputMediaPhoto(media=image.image_url, caption=caption))
            await self.app.bot.send_media_group(chat_id=chat_id, media=media_group)

    async def _create_poll(self, event: mibo_events.MiboPollResponse) -> None:
        '''
        Make a poll.
        Property verification is done elsewhere - it is assumed that the poll is valid here.
        '''
        chat_id: str = event.chat_id
        poll: wrapper.PollWrapper = event.poll

        await self.app.bot.send_poll(
            chat_id=chat_id,
            question=poll.question,
            options=poll.options,
            allows_multiple_answers=poll.multiple_choice,
            correct_option_id=poll.correct_option_idx if poll.correct_option_idx != -1 else None,
            explanation=poll.explanation if poll.explanation else None
        )

    async def _debug(self, update: Update, context: CallbackContext):
        '''
        Sends a debug message.
        '''
        await context.bot.send_message(update.effective_chat.id, 'Debug OK')

    async def _welcome(self, update: Update, context: CallbackContext):
        '''
        Sends a message to the group when the bot joins.
        '''
        chat = update.effective_chat
        old_status = update.my_chat_member.old_chat_member.status
        new_status = update.my_chat_member.new_chat_member.status

        if chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            # Bot was added to a group or supergroup
            if old_status in [ChatMember.LEFT, ChatMember.BANNED] and new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR]:
                welcome_message = (
                    f"Hello! I'm Mibo, your AI assistant. You can mention me (@{context.bot.username}) "
                    f"in your messages or reply to my messages to interact with me."
                )
                await context.bot.send_message(chat_id=chat.id, text=welcome_message)
            
            # Bot was removed from a group
            elif old_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR] and new_status in [ChatMember.LEFT, ChatMember.BANNED]:
                # Could log this event or perform cleanup if needed
                pass

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.CRITICAL  # Changed from logging.INFO to logging.DEBUG
)
# For more detailed python-telegram-bot logs:
logging.getLogger("telegram.ext").setLevel(logging.CRITICAL)

async def main() -> None:
    token = tools.Tool.TELEGRAM_KEY
    db_path = tools.Tool.DB_PATH

    bot = Mibo(token, db_path)
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())