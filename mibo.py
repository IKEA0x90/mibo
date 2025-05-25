import asyncio
import sys
import signal
import openai
import logging
import random
import re

import datetime as dt
from typing import List, Dict
from telegram import Update, Chat, ChatMember, InputFile, InputMediaPhoto
from telegram.ext import Application, CallbackContext, CommandHandler, MessageHandler, ChatMemberHandler, filters
from telegram.constants import ChatAction

from events import event_bus, mibo_events, system_events, assistant_events, conductor_events
from core import assistant, database, conductor, wrapper
from services import tools

class Mibo:
    def __init__(self, token: str, db_path: str = 'env'):
        self.token = token
        self.start_datetime = dt.datetime.now(dt.timezone.utc)

        self.bus = event_bus.EventBus()
        self.db = database.Database(self.bus, db_path)
        self.conductor = conductor.Conductor(self.bus)

        self.key = tools.Tool.OPENAI_KEY
        
        self.client = None
        self.assistants = {} 
        self.app = None

        self.typing_tasks: Dict[int, asyncio.Task] = {}

        self._prepare(token)
        print(f'Mibo is alive! It is {self.start_datetime.hour}:{self.start_datetime.minute}:{self.start_datetime.second} UTC.')

    def _prepare(self, token: str):
        '''
        Prepare the bot by loading the database, getting the openai client, and setting up signal handlers.
        '''
        self.db.initialize_sync()

        self.client = openai.OpenAI(api_key=self.key)

        template_assistant = self.client.beta.assistants.retrieve(tools.Tool.MIBO_ID).to_dict()
        cat_assistant = self.client.beta.assistants.retrieve(tools.Tool.CAT_ASSISTANT_ID).to_dict()
        image_assistant = self.client.beta.assistants.retrieve(tools.Tool.IMAGE_ASSISTANT_ID).to_dict()
        poll_assistant = self.client.beta.assistants.retrieve(tools.Tool.POLL_ASSISTANT_ID).to_dict()
        property_assistant = self.client.beta.assistants.retrieve(tools.Tool.PROPERTY_ASSISTANT_ID).to_dict()
        memory_assistant = self.client.beta.assistants.retrieve(tools.Tool.MEMORY_ASSISTANT_ID).to_dict()

        self.templates = {'template': template_assistant,
                    'cat_template': cat_assistant, 
                    'image_template': image_assistant, 
                    'poll_template': poll_assistant, 
                    'property_template': property_assistant, 
                    'memory_template': memory_assistant}

        self.assistants = assistant.initialize_assistants(self.db, self.client, self.bus, self.templates, self.start_datetime)
        
        # Register event listeners
        self._register()

        self.app = Application.builder().token(self.token).build()

        # Create stop event for graceful shutdown
        self.stop_event = asyncio.Event()

        self._register_handlers()
        self._system_signals()

    def _register(self):
        self.bus.register(assistant_events.AssistantResponse, self._parse_message)
        self.bus.register(mibo_events.MiboMessageResponse, self._send_message)
        self.bus.register(mibo_events.MiboPollResponse, self._create_poll)
        self.bus.register(conductor_events.NewChatPush, self._create_assistant)

    async def run(self):
        '''
        Start the bot
        '''
        # re-initialize for async cursor
        await self.db.initialize()
        
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

    async def _create_assistant(self, event: conductor_events.NewChatPush):
        try:
            chat = event.chat
            chat_id = chat.chat_id

            if chat_id in self.assistants:
                await self.bus.emit(mibo_events.AssistantCreated(chat_id=chat_id, event_id=event.event_id))
                return

            new_assistant = assistant.Assistant(
                chat_id, 
                self.client, 
                self.bus, 
                self.templates, 
                self.start_datetime,
                chat=chat,
                assistant_type=tools.Tool.MIBO
            )
                
            self.assistants[chat_id] = new_assistant
            
            await self.bus.emit(mibo_events.AssistantCreated(chat_id=chat_id, event_id=event.event_id))
    
        except Exception as e:
            raise e
            #await self.bus.emit(system_events.ChatErrorEvent(f"Couldn't create an instance of you for the new friend.", e))

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
        
        chat_id = str(update.effective_chat.id)

        old_task = self.typing_tasks.pop(chat_id, None)
        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass
        
        def typing():
            if chat_id not in self.typing_tasks or self.typing_tasks[chat_id].done():
                self.typing_tasks[chat_id] = asyncio.create_task(self._simulate_typing(chat_id))
        
        event = await self.bus.emit(mibo_events.MiboMessage(update, context, start_datetime=self.start_datetime, typing=typing))

    async def _system_message(self, chat_id, system_message):
        '''
        Forces the bot to send a message to a chat, possibly appending a system message to the prompt.
        '''
        event = await self.bus.emit(mibo_events.MiboSystemMessage(chat_id, system_message, start_datetime=self.start_datetime))

    async def _parse_message(self, event: assistant_events.AssistantResponse):
        '''
        Parses a message and calls the correct responder.
        '''
        chat_id = str(event.message.chat_id)
        message: wrapper.MessageWrapper = event.message

        task = self.typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        message_text: str = message.message
        message_images: List[wrapper.ImageWrapper] = message.get_images()
        message_sticker: wrapper.StickerWrapper = message.get_sticker()
        message_poll: wrapper.PollWrapper = message.get_poll()

        if message_text or message_images:
            response = mibo_events.MiboMessageResponse(chat_id, message_text, message_images)
            await self.bus.emit(response)

        if message_sticker:
            response = system_events.ChatErrorEvent(chat_id, 'Stickers are not supported yet.')
            await self.bus.emit(response)

        if message_poll:
            response = mibo_events.MiboPollResponse(chat_id, message_poll)
            await self.bus.emit(response)    
        
    @staticmethod
    def parse_text(text: str) -> List[str]:
        '''
        Parse the text for custom delimiters.
        '''
        prefix = tools.Tool.MIBO_MESSAGE  # 'mibo:'
        pattern = rf'^(?:{prefix.rstrip()}\s+)+'
        text2 = text.strip()

        if re.match(pattern, text, flags=re.IGNORECASE):
            text2 = re.sub(pattern, '', text, flags=re.IGNORECASE)

        text_list = text2.split('\n')

        return text_list

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
        
        text_list = []

        if text:
            text_list = self.parse_text(text)

        # If only text
        if text_list and not images:
            for t in text_list:
                await self.app.bot.send_message(chat_id=chat_id, text=t)
                await asyncio.sleep(random.uniform(0.5, 3))
            return

        # If only images
        if images and not text:
            media_group = [
                self.app.bot._wrap_input_media_photo(image.image_url) for image in images
            ]
            await self.app.bot.send_media_group(chat_id=chat_id, media=media_group)
            return

        # If both text and images: send as album, text as caption to first image
        if images and text_list:
            media_group = []
            for idx, image in enumerate(images):
                caption = text_list[0] if idx == 0 else None
                media_group.append(InputMediaPhoto(media=image.image_url, caption=caption))
            await self.app.bot.send_media_group(chat_id=chat_id, media=media_group)

            for t in text_list[1:]:
                await self.app.bot.send_message(chat_id=chat_id, text=t)
                await asyncio.sleep(random.uniform(0.5, 3))

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

    async def _simulate_typing(self, chat_id: int):
        try:
            while True:
                await self.app.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.CRITICAL
)
logging.getLogger("telegram.ext").setLevel(logging.CRITICAL)

async def main() -> None:
    token = tools.Tool.TELEGRAM_KEY
    db_path = tools.Tool.DB_PATH

    bot = Mibo(token, db_path)
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())