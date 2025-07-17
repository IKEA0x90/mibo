import asyncio
import sys
import signal
import openai
import logging
import random
import re
import traceback
import uuid

import datetime as dt
from typing import List, Dict
from telegram import Update, Chat, ChatMember, InputFile, InputMediaPhoto, Message, User
from telegram.ext import Application, CallbackContext, CommandHandler, MessageHandler, ChatMemberHandler, filters
from telegram.constants import ChatAction

from events import event_bus, mibo_events, system_events, assistant_events, conductor_events
from core import assistant, database, conductor, wrapper
from services import tools, templates

class Mibo:
    def __init__(self, token: str, db_path: str = 'env'):
        self.token = token
        self.start_datetime = dt.datetime.now(dt.timezone.utc)

        # load the environment first to catch early errors
        try:
            _ = tools.Tool()
        except TypeError:
            exit(1)

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
        self.bus.register(system_events.ErrorEvent, self._handle_exception)

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
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error=f"Couldn't create Mibo instance for the new chat.", e=e, tb=tb, event_id=event.event_id, chat_id=event.chat.chat_id))

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

    async def _system_message(self, chat_id, chat_name, system_message):
        '''
        Forces the bot to send a message to a chat, possibly appending a system message to the prompt.
        '''
        def typing():
            if chat_id not in self.typing_tasks or self.typing_tasks[chat_id].done():
                self.typing_tasks[chat_id] = asyncio.create_task(self._simulate_typing(chat_id))

        user = User(id=0, first_name="System", is_bot=True)
        chat = Chat(id=chat_id, type=Chat.PRIVATE, title=chat_name)
        message = Message(
            message_id=uuid.uuid4().int,
            date=dt.datetime.now(dt.timezone.utc),
            chat=chat,
            from_user=user,
            text=system_message
        )
        update = Update(update_id=uuid.uuid4().int, message=message)
        event = mibo_events.MiboMessage(update=update, context=None, start_datetime=self.start_datetime, typing=typing)
        event.system = True
        await self.bus.wait(event, assistant_events.AssistantResponse)

        old_task = self.typing_tasks.pop(chat_id, None)
        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass

    async def _parse_message(self, event: assistant_events.AssistantResponse):
        '''
        Parses a message and calls the correct responder.
        '''
        messages: wrapper.Wrapper = event.messages

        if not messages:
            return
        
        chat_id = messages[0].chat_id

        task = self.typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        message_text: str = ''
        message_images: List[wrapper.ImageWrapper] = []

        for message in messages:
            if isinstance(message, wrapper.MessageWrapper):
                message_text: str = message._remove_prefix(message.message)

            if isinstance(message, wrapper.ImageWrapper):
                message_images.append(message)

        if message_text or message_images:
            response = mibo_events.MiboMessageResponse(chat_id, message_text, message_images)
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

        text_list = text2.split('|n|')

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
                await asyncio.sleep(self.typing_delay(t)) # average of 0.5 for 10 characters and 5 for 100 characters
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
                await asyncio.sleep(self.typing_delay(t))

    def typing_delay(self, text: str):
        length = len(text)
        avg_cpm = 500
        jitter_sd = 0.08
        # Ramp from 0 to 0.3 seconds over the first 16 characters
        reaction = random.uniform(0.0, 0.3) * min(length, 16) / 16
        base = (60.0 / avg_cpm) * length
        multiplier = max(0.2, random.gauss(1.0, jitter_sd))
        return max(0.0, reaction + base * multiplier)

    async def _handle_exception(self, event: system_events.ErrorEvent) -> None:
        '''
        Print exception logs.
        '''
        error = event.error
        e = event.e
        tb = event.tb

        print(f"{error}")

        if tb:
            traceback.print_exception(type(e), e, tb)

    async def _notify_creator(self, events: Dict) -> None:
        '''
        Notify me about an event.
        '''
        admin_chat = tools.Tool.SYSTEM_CHAT

        try:
            if event := events.get('join'):
                group_name = event.get('group_name', 'Unknown Group')
                admin = event.get('admin', False)

                message = templates.WelcomeNotification(group_name=group_name, admin=admin)

                # Send the notification to the creator
                await self._system_message(admin_chat, "Admin Notifications", str(message))

            # Cancel the typing simulation for the creator notification
            old_task = self.typing_tasks.pop(admin_chat, None)
            if old_task and not old_task.done():
                old_task.cancel()
                try:
                    await old_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error="Creator unreachable.", e=e, tb=tb))

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
        Sends a message to the group when the bot joins or leaves.
        '''
        chat = update.effective_chat
        old_status = update.my_chat_member.old_chat_member.status
        new_status = update.my_chat_member.new_chat_member.status
        group_name = chat.effective_name

        update_datetime = update.my_chat_member.date
        if update_datetime < self.start_datetime:
            return

        events = {}

        if chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            # Bot was added to a group or supergroup
            if old_status in [ChatMember.LEFT, ChatMember.BANNED] and new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR]:
                
                is_admin = (new_status == ChatMember.ADMINISTRATOR)

                message = templates.WelcomeMessage(group_name=group_name, admin=is_admin)

                await self._system_message(chat_id=chat.id, chat_name=group_name, system_message=str(message))

                events['join'] = {
                    'group_name': group_name,
                    'admin': is_admin
                }

                await self._notify_creator(events)

            # Bot was removed from a group
            elif old_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR] and new_status in [ChatMember.LEFT, ChatMember.BANNED]:
                # Log or handle cleanup if needed
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