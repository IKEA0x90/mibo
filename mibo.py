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
from typing import List, Dict, Type
from telegram import Update, Chat, ChatMember, InputMediaPhoto, Message, User
from telegram.ext import Application, CallbackContext, CommandHandler, MessageHandler, ChatMemberHandler, filters
from telegram.constants import ChatAction

from events import event_bus, mibo_events, system_events, assistant_events
from core import assistant, conductor, wrapper, ref
from services import prompt_enum, variables

class Mibo:
    def __init__(self, token: str, db_path: str = 'memory'):
        self.token: str = token
        self.start_datetime: dt.datetime = dt.datetime.now(dt.timezone.utc)

        # load the environment first to catch early errors
        try:
            _ = variables.Variables()
        except TypeError:
            exit(1)

        self.clients: List[openai.OpenAI] = []
        self.local_clients: List[openai.OpenAI] = []

        self.bus: event_bus.EventBus = event_bus.EventBus()
        self.ref: ref.Ref = ref.Ref(self.bus, db_path, self.start_datetime)
        self.conductor: conductor.Conductor = conductor.Conductor(self.bus, self.ref)

        self.key: str = variables.Variables.OPENAI_KEY

        self.app: Application = None
        self.typing_tasks: Dict[int, asyncio.Task] = {}

        self._prepare()
        print(f'Mibo is alive! It is {self.start_datetime.hour}:{self.start_datetime.minute}:{self.start_datetime.second} UTC.')

    def _prepare(self):
        '''
        Prepare the bot by loading the database, getting the openai client, and setting up signal handlers.
        '''
        self.clients: Dict[str, openai.OpenAI] = {
            'openai': openai.OpenAI(api_key=self.key),
            'local': openai.OpenAI(api_key=self.key, base_url=f"http://{variables.Variables.LOCAL_API_HOST}:{variables.Variables.LOCAL_API_PORT}/v1")
        }

        self.assistant = assistant.Assistant(self.clients, self.bus, self.ref, self.start_datetime)

        # Register event listeners
        self._register()

        self.app = Application.builder().token(self.token).build()

        # Create stop event for graceful shutdown
        self.stop_event = asyncio.Event()

        self._register_handlers()
        self._system_signals()

    def _register(self):
        '''
        Register event listeners
        '''
        self.bus.register(assistant_events.AssistantResponse, self._parse_message)
        self.bus.register(system_events.ErrorEvent, self._handle_exception)

    async def run(self):
        '''
        Start the bot
        '''
        # re-initialize for async
        await self.ref.initialize()
        
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
        #self.app.add_handler(ChatMemberHandler(self._welcome, ChatMemberHandler.MY_CHAT_MEMBER))

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
        await self.ref.close()

        print('Shutdown complete.')

    async def _simulate_typing(self, chat_id: int):
        try:
            while True:
                await self.app.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    def _get_typing(self, chat_id: str):
        def typing():
            if chat_id not in self.typing_tasks or self.typing_tasks[chat_id].done():
                self.typing_tasks[chat_id] = asyncio.create_task(self._simulate_typing(chat_id))

        return typing
    
    async def _pop_typing(self, chat_id: str):
        task = self.typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

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

        #await self._pop_typing(chat_id)
        typing = self._get_typing(chat_id)
        
        event = await self.bus.emit(mibo_events.NewMessageArrived(update, context, typing=typing))

    async def _system_message(self, chat_id: str, system_message: str, **kwargs):
        '''
        Forces the bot to send a message to a chat, possibly appending a system message to the prompt.
        '''
        #await self._pop_typing(chat_id)
        typing = self._get_typing(chat_id)

        chat_name: str = kwargs.get('chat_name', '')

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
        event = mibo_events.NewMessageArrived(update=update, context=None, typing=typing)
        event.system = True

        await self.bus.emit(event)

    async def _event_message(self, chat_id: str, event_prompt: Type[prompt_enum.PromptEnum], replacers: Dict[str, str] = {}, **kwargs):
        try:
            prompts: Dict[prompt_enum.PromptEnum, str] = await self.ref.get_prompts(chat_id)
            prompt = prompts.get(event_prompt, None)

            if not prompt:
                return
            
            if replacers:
                for replacer_key, replacer_value in replacers.items():
                    key = '{' + replacer_key + '}'
                    prompt = prompt.replace(key, replacer_value)

            self._system_message(chat_id=chat_id, system_message=prompt, **kwargs)

        except Exception as e:
            self.bus.emit(system_events.ErrorEvent(error="Something's wrong with getting prompts.", e=e, tb=None, event_id=None, chat_id=chat_id))

    async def _parse_message(self, event: assistant_events.AssistantResponse):
        '''
        Parses a message and calls the correct responder.
        '''
        messages: wrapper.Wrapper = event.messages

        if not messages:
            return
        
        chat_id = messages[0].chat_id

        message_text: str = ''
        message_images: List[wrapper.ImageWrapper] = []

        for message in messages:
            if isinstance(message, wrapper.MessageWrapper):
                message_text: str = message._remove_prefixes(message.message, await self.ref.get_assistant_names(chat_id))

            if isinstance(message, wrapper.ImageWrapper):
                message_images.append(message)

        if message_text or message_images:
            await self._send_message(chat_id, message_text, message_images)

    @staticmethod
    def parse_text(text: str) -> List[str]:
        '''
        Parse the text for custom delimiters.
        '''
        text = text.strip()
        text_list = text.split('|n|')

        # remove empty strings and whitespace-only strings
        filtered_list = [s for s in text_list if s.strip()]

        return filtered_list

    async def _send_message(self, chat_id: str, text: str, images: List[wrapper.ImageWrapper]) -> None:
        '''
        Send the text and images from the response message.
        Text and/or images may be empty - in that case, only the non-empty item is sent.
        If both are empty, nothing is sent.
        If images are sent, they are combined into an album and the message is sent appended to the first image (like users do).
        '''
        if not text and not images:
            return
        
        text_list = []

        if text:
            text_list = self.parse_text(text)

        typing = self._get_typing(chat_id)

        # If only text
        if text_list and not images:
            for t in text_list:
                await self._pop_typing(chat_id)

                await self.app.bot.send_message(chat_id=chat_id, text=t)
                await asyncio.sleep(variables.Variables.typing_delay(t)) # average of 0.5 for 10 characters and 5 for 100 characters

                typing()
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
                await self._pop_typing(chat_id)

                await self.app.bot.send_message(chat_id=chat_id, text=t)
                await asyncio.sleep(variables.Variables.typing_delay(t))

                typing()
        
        await self._pop_typing(chat_id)

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

        if chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            if old_status in [ChatMember.LEFT, ChatMember.BANNED] and new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR]:
                is_admin = (new_status == ChatMember.ADMINISTRATOR)

                admin_replacer = 'an admin' if is_admin else 'a member'
                replacers = {
                    'admin': admin_replacer,
                    'group_name': group_name
                }

                await self._event_message(chat_id=chat.id, event_prompt=prompt_enum.WelcomePrompt, replacers=replacers, chat_name=group_name)

            elif old_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR] and new_status in [ChatMember.LEFT, ChatMember.BANNED]:
                pass    

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.CRITICAL
)
logging.getLogger("telegram.ext").setLevel(logging.CRITICAL)

async def main() -> None:
    token = variables.Variables.TELEGRAM_KEY
    db_path = variables.Variables.DB_PATH

    bot = Mibo(token, db_path)
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())