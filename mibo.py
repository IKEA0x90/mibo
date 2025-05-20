import asyncio
import os
import signal
import openai

import datetime as dt
from typing import List, Optional
from telegram import Update, Chat, ChatMember, InputFile
from telegram.ext import Application, CallbackContext, CommandHandler, MessageHandler, ChatMemberHandler, filters

from events import event_bus, mibo_events, system_events, assistant_events
from core import assistant, database, conductor, wrapper
from services import tools

class Mibo:
    def __init__(self, token: str, db_path: str = 'env'):
        self.token = token
        self.start_datetime = dt.datetime.now(dt.timezone.utc).timestamp()

        self.db = database.Database(db_path)
        self.bus = event_bus.EventBus()
        self.conductor = conductor.Conductor(self.bus)

        self.system_chat: str = os.environ['SYSTEM_CHAT']
        self.key = os.environ['OPENAI_API_KEY']
        
        self.client = None
        self.assistants = {} 
        self.app = None

        self._prepare(token)

    def _prepare(self, token: str):
        '''
        Prepare the bot by loading the database, getting the openai client, and setting up signal handlers.
        '''
        self.db.initialize()
        
        self.client = openai.AsyncOpenAI(api_key=self.key)
        temporary_client = openai.OpenAI(api_key=self.key)

        template_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.MIBO_ID)
        cat_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.CAT_ASSISTANT_ID)
        image_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.IMAGE_ASSISTANT_ID)
        poll_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.POLL_ASSISTANT_ID)
        sticker_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.STICKER_ASSISTANT_ID)
        property_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.PROPERTY_ASSISTANT_ID)
        memory_assistant = temporary_client.beta.assistants.retrieve(tools.Tool.MEMORY_ASSISTANT_ID)

        self.templates = {'template': template_assistant,
                    'cat_template': cat_assistant, 
                    'image_template': image_assistant, 
                    'poll_template': poll_assistant, 
                    'sticker_template': sticker_assistant, 
                    'property_template': property_assistant, 
                    'memory_template': memory_assistant}

        self.assistants = assistant.initialize_assistants(self.db, self.client, self.bus, self.templates, self.start_datetime)
        
        # Register event listeners
        self.bus.register(assistant_events.AssistantResponse, self._parse_message)
        self.bus.register(mibo_events.MiboMessageResponse, self._handle_message_response)
        self.bus.register(mibo_events.MiboStickerResponse, self._handle_sticker_response)
        self.bus.register(mibo_events.MiboPollResponse, self._handle_poll_response)
        
        self._register_handlers()
        self.app = Application.builder().token(self.token).build()

        # Create stop event for graceful shutdown
        self.stop_event = asyncio.Event()

        self._system_signals()

    async def run(self, token: str):
        '''
        Start the bot
        '''
        await self.app.initialize()
        polling_task = asyncio.create_task(self.app.start())

        # block until _system_signals() flips the flag
        await self.stop_event.wait()

        # kill Mibo (oh no!)
        await self._shutdown(polling_task)

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
        loop = asyncio.get_running_loop()

        def _on_signal(sig: signal.Signals) -> None:
            # Flip the in‑memory flag so `await self.stop_event.wait()` in the main task unblocks.
            self.stop_event.set()

            # inform the rest of the application through the EventBus using the sync method
            self.bus.emit_sync(system_events.ShutdownEvent(sig=sig))

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_signal, sig)
        
    async def _shutdown(self, polling_task: asyncio.Task):
        print('Shutting down...')

        # stop Telegram
        await self.app.stop()
        await self.app.shutdown()

        # close services
        await self.bus.close()
        await self.db.close()

        # polling task cancellation
        polling_task.cancel()
        await asyncio.gather(polling_task, return_exceptions=True)

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
            # send the text and images from the response message
            # text and/or images may be empty - in that case, only the non-empty item is sent
            # if both are empty, nothing is sent

            response = mibo_events.MiboMessageResponse(chat_id, message_text, message_images)
            self.bus.emit(response)

        if message_sticker:
            response = mibo_events.MiboStickerResponse(chat_id, message_sticker)
            self.bus.emit(response)

        if message_poll:
            response = mibo_events.MiboPollResponse(chat_id, message_poll)
            self.bus.emit(response)    async def _handle_message_response(self, event: mibo_events.MiboMessageResponse):
        '''
        Handles text and image message responses from the assistant.
        Sends text and images to the chat via Telegram API.
        '''
        chat_id: str = event.chat_id
        text: str = event.text
        images: List[wrapper.ImageWrapper] = event.images
        
        # Send the text message if it exists
        if text and text.strip():
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode='Markdown'
                )
            except Exception as e:
                # If Markdown parsing fails, try sending as plain text
                print(f"Failed to send message with Markdown formatting: {e}")
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=text
                )
        
        # Send each image if they exist
        if images and len(images) > 0:
            for image in images:
                try:
                    if image.image_url:
                        await self.app.bot.send_photo(
                            chat_id=chat_id,
                            photo=image.image_url,
                            caption=image.image_description if image.image_description else None
                        )
                    elif image.image_base64:
                        # For base64 images, we need to convert them to bytes
                        import base64
                        from io import BytesIO
                        
                        image_bytes = BytesIO(base64.b64decode(image.image_base64))
                        await self.app.bot.send_photo(
                            chat_id=chat_id,
                            photo=image_bytes,
                            caption=image.image_description if image.image_description else None
                        )
                except Exception as e:
                    print(f"Failed to send image: {e}")
                    # Notify the user that an image couldn't be sent
                    await self.app.bot.send_message(
                        chat_id=chat_id,
                        text="Sorry, I couldn't send an image."
                    )

    async def _handle_sticker_response(self, event: mibo_events.MiboStickerResponse):
        '''
        Handles sticker responses from the assistant.
        Sends stickers to the chat via Telegram API.
        '''
        chat_id: str = event.chat_id
        sticker: wrapper.StickerWrapper = event.sticker
        
        if sticker and sticker.key_emoji:
            try:
                # In the latest python-telegram-bot, we need to use a different approach
                # for sending stickers based on emoji
                
                # For a production bot, you might want to:
                # 1. Maintain a mapping of emojis to sticker file_ids
                # 2. Use a sticker search API if available
                # 3. Create custom stickers for common emojis
                
                # As a fallback, we'll send the emoji as text
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=sticker.key_emoji
                )
            except Exception as e:
                print(f"Failed to send sticker: {e}")
                # Fallback to sending as text
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=sticker.key_emoji
                )

    async def _handle_poll_response(self, event: mibo_events.MiboPollResponse):
        '''
        Handles poll responses from the assistant.
        Creates and sends polls to the chat via Telegram API.
        '''
        chat_id: str = event.chat_id
        poll: wrapper.PollWrapper = event.poll
        
        if poll and poll.question and poll.options:
            if poll.correct_option_idx >= 0:
                # This is a quiz poll (with a correct answer)
                await self.app.bot.send_poll(
                    chat_id=chat_id,
                    question=poll.question,
                    options=poll.options,
                    type='quiz',
                    correct_option_id=poll.correct_option_idx,
                    explanation=poll.explanation if poll.explanation else None,
                    is_anonymous=False
                )
            else:
                # This is a regular poll
                await self.app.bot.send_poll(
                    chat_id=chat_id,
                    question=poll.question,
                    options=poll.options,
                    is_anonymous=False,
                    allows_multiple_answers=poll.multiple_choice
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
            if old_status in [ChatMember.LEFT, ChatMember.KICKED] and new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR]:
                welcome_message = (
                    f"Hello! I'm Mibo, your AI assistant. You can mention me (@{context.bot.username}) "
                    f"in your messages or reply to my messages to interact with me."
                )
                await context.bot.send_message(chat_id=chat.id, text=welcome_message)
            
            # Bot was removed from a group
            elif old_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR] and new_status in [ChatMember.LEFT, ChatMember.KICKED]:
                # Could log this event or perform cleanup if needed
                pass

async def main() -> None:
    token = os.environ['mibo']
    bot = Mibo(token)
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())