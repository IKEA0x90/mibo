import asyncio
import sys
import datetime as dt

from io import BytesIO
from PIL import Image
from typing import cast
from telegram import Update, Message, MessageEntity
from telegram.ext import CallbackContext

from events import event, event_bus, conductor_events, db_events, system_events, mibo_events
from core import wrapper
from services import tools

class Conductor:
    '''
    A layer between telegram and the services.
    Captures the raw event, parses it into a MessageWrapper, and adds it back to the bus.
    '''
    def __init__(self, bus):
        self.bus: event_bus.EventBus = bus
        self.username: str = tools.Tool.MIBO
        self._register()

    def _register(self):
        self.bus.register(mibo_events.MiboMessage, self._capture_message)

    async def _capture_message(self, event: mibo_events.MiboMessage):
        '''
        Listens to new messages sent to chats and processes them into Wrappers.
        Then, calls Mibo.
        ''' 
        system_message = hasattr(event, 'system')

        try:
            update: Update = event.update
            start_datetime: dt.datetime = event.start_datetime
            context: CallbackContext = event.context

            chat = update.effective_chat
            message: Message = update.message
            user = update.message.from_user
            
            if not chat or not message or not user:
                return

            chat_id = chat.id
            message_id = message.message_id
            chat_name = chat.effective_name or ''

            if not chat_id or not message_id:
                return
        
        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error="Woah! Somehow, this telegram message can't be parsed.", e=e, tb=tb, event_id=event.event_id))

        try:
            user = user.username or user.first_name
            if system_message:
                role = 'developer'
            else:
                role = 'assistant' if user == self.username else 'user'

            message_text = message.text or ''
            
            entities = message.parse_entities(types=[
                'mention',
                'url'
            ])

            ping = False

            if chat.type == chat.PRIVATE or system_message:
                ping = True 

            if entities:
                for entity, value in entities.items():
                    entity = cast(MessageEntity, entity) # for type hinting

                    if entity.type == 'mention':
                        if value.startswith('@') and value[1:] == tools.Tool.MIBO_PING:
                            ping = True

                    elif entity.type == 'url':
                        # special url processing
                        pass
            
            reply_message = message.reply_to_message

            reply_id = reply_message.message_id if reply_message else None

            if reply_id and (reply_message.from_user.id == context.bot.id):
                ping = True

            if f'{tools.Tool.MIBO}' in message_text.lower() or f'{tools.Tool.MIBO_RU}' in message_text.lower():
                ping = True
                
            datetime: dt.datetime = message.date.astimezone(dt.timezone.utc)

            message_wrapper = wrapper.MessageWrapper(message_id=message_id, chat_id=chat_id, role=role, user=user, message=message_text, ping=ping, reply_id=reply_id, datetime=datetime, chat_name=chat_name)
            content = await self._look_for_content(update, context, event)

            wrappers = [message_wrapper] + content
            push_request = conductor_events.WrapperPush(wrappers, chat_id=chat_id, event_id=event.event_id)
            
            chat_response = await self.bus.wait(push_request, db_events.NewChatAck)
            chat_wrapper = chat_response.chat

            push_request = conductor_events.NewChatPush(chat_wrapper, event_id=event.event_id)
            await self.bus.wait(push_request, mibo_events.AssistantCreated)

            await self.bus.emit(conductor_events.AssistantRequest(chat_id=chat_id, message=message_wrapper, event_id=event.event_id, typing=event.typing, system=system_message))

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error="Something's wrong with passing the messages from telegram to you.", e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))

    # ---------------------------------- #

    async def _look_for_content(self, update: Update, context: CallbackContext, parent_event: event.Event):
        message: Message = update.effective_message
        content = []

        if message.photo or (message.document and message.document.mime_type and message.document.mime_type.startswith('image/')):
            image_list = await self._download_images_telegram(update, context, parent_event)
            content.extend(image_list)

        return content

    async def _download_images_telegram(self, update: Update, context: CallbackContext, parent_event: event.Event):
        '''
        Download all image files (photos or image documents) from a Telegram message and return a list of ImageWrappers.
        '''
        try:
            chat = update.effective_chat
            message: Message = update.effective_message

            file_bytes = []

            # Handle photos - only get the largest size (last in the list)
            if message.photo:
                largest_photo = message.photo[-1]  # Last photo is the largest
                file = await context.bot.get_file(largest_photo.file_id)
                photo_bytes = await file.download_as_bytearray()
                file_bytes.append(photo_bytes)

            # Handle single image document
            elif message.document and message.document.mime_type and message.document.mime_type.startswith('image/'):
                file = await context.bot.get_file(message.document.file_id)
                doc_bytes = await file.download_as_bytearray()
                file_bytes.append(doc_bytes)

            # Resize and get image bytes asynchronously
            async def process_image(img_bytes):
                def sync_process():
                    with Image.open(BytesIO(img_bytes)) as img:
                        # Resize the image keeping aspect ratio, with max dimension of 768px
                        width, height = img.size
                        max_size = 768 # this size maximizes cost efficiency and quality
                        
                        if width > height and width > max_size:
                            new_width = max_size
                            new_height = int(height * (max_size / width))
                        elif height > max_size:
                            new_height = max_size
                            new_width = int(width * (max_size / height))
                        else:
                            new_width, new_height = width, height
                            
                        if new_width != width or new_height != height:
                            img = img.resize((new_width, new_height), Image.BICUBIC)
                        
                        if img.mode not in ('RGB', 'L'):
                            img = img.convert('RGB')

                        buffered = BytesIO()
                        img.save(buffered, format='JPEG', quality=85)
                        img_bytes = buffered.getvalue()
                        
                    wrap = wrapper.ImageWrapper(new_width, new_height, img_bytes)
                    return wrap
                
                return await asyncio.to_thread(sync_process)
            
            images = await asyncio.gather(*[process_image(img_bytes) for img_bytes in file_bytes])

            image_wrappers = [wrapper.ImageWrapper(message.id, chat.id, image.x, image.y, image.image_bytes) for image in images]
            return image_wrappers
        
        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error='Failed to download image.', e=e, tb=tb, event_id=parent_event.event_id, chat_id=chat.id))