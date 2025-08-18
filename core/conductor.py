import asyncio
import random
import sys
import datetime as dt

from io import BytesIO
from PIL import Image
from typing import Dict, cast
from telegram import Chat, Update, Message, MessageEntity, User
from telegram.ext import CallbackContext

from events import event, event_bus, conductor_events, mibo_events, system_events
from core import ref, window, wrapper
from services import prompt_enum, variables

class Conductor:
    '''
    A layer between telegram and the services.
    Captures the raw event, parses it into a MessageWrapper, and adds it back to the bus.
    '''
    def __init__(self, bus, referrer: ref.Ref):
        self.bus: event_bus.EventBus = bus
        self.ref: ref.Ref = referrer

        self._register()

    def _register(self):
        self.bus.register(mibo_events.NewMessageArrived, self._capture_message)

    async def _capture_message(self, event: mibo_events.NewMessageArrived):
        '''
        Listens to new messages sent to chats and processes them into Wrappers.
        Then, calls Mibo.
        ''' 
        update: Update = event.update
        context: CallbackContext = event.context

        try:
            chat: Chat = update.effective_chat
            message: Message = update.effective_message

            if not chat or not message:
                return {}

            user: User = message.from_user
            if not user:
                return {}
            
            chat_id: str = chat.id
            message_id: str = message.message_id
            chat_name: str = chat.effective_name or ''

            if not chat_id or not message_id:
                return {}

            chat_id = message.chat.id
            chat_type = message.chat.type
            chat_name = message.chat.effective_name or ''

            message_id = message.message_id
            message_text = message.text
            message_caption = message.caption

            user = message.from_user
            user_id = user.id
            username = user.username or user.first_name

            entities = message.parse_entities()
            caption_entities = message.parse_caption_entities()

            ping = False
            system_message = hasattr(event, 'system')

            if system_message:
                role = 'system'
            else:
                role = 'assistant' if user == self.username else 'user'

            message_text = message_text or message_caption or ''

            if chat_type == Chat.PRIVATE or system_message:
                ping = True 

            if entities or caption_entities:
                for entity, value in {**entities.items(), **caption_entities.items()}:
                    entity = cast(MessageEntity, entity) # for type hinting

                    if entity.type == 'mention':
                        if value.startswith('@') and value[1:] == variables.Variables.NICKNAME:
                            ping = True

                    elif entity.type == 'url':
                        # special url processing
                        pass
            
            reply_message = message.reply_to_message
            reply_id = reply_message.message_id if reply_message else None

            quote = reply_message.quote if reply_message else None
            quote_text = quote.text if quote else None

            if reply_id and (reply_message.from_user.id == context.bot.id):
                ping = True

            # if any of string names is in the text
            names = self.ref.get_assistant_names(chat_id)
            if any(name in message_text for name in names):
                ping = True
                
            datetime: dt.datetime = message.date.astimezone(dt.timezone.utc)

            message_wrapper = wrapper.MessageWrapper(id=message_id, chat_id=chat_id, message=message_text, ping=ping, 
                                                     reply_id=reply_id, quote=quote_text,
                                                     datetime=datetime, role=role, user=user)
            
            content = await self._look_for_content(update, context, event)

            c: wrapper.Wrapper
            for c in content:
                c.role = role
                c.user = user
                c.ping = ping

            wrappers = ([message_wrapper] if message_wrapper.message else []) + content

            if not wrappers:
                raise ValueError("Wrapper list is somehow empty. This probably shouldn't happen.")
            
            wdw: window.Window = await self.ref.add_message(chat_id, wrappers, chat_name=chat_name)
            request: Dict = await self.ref.get_request(chat_id)
            prompts: Dict[prompt_enum.PromptEnum, str] = await self.ref.get_prompts(chat_id)
            special_fields: Dict = self.ref.get_special_fields(chat_id)

            chance: int = await self.ref.get_chance(chat_id)
            random_chance = random.randint(1, 100)

            respond = wdw.ready and ((random_chance <= chance) or ping) and not message_caption

            if respond:
                new_message_event = conductor_events.CompletionRequest(wdw=wdw, request=request, prompts=prompts, special_fields=special_fields)
                await self.bus.emit(new_message_event)

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error="Something's wrong with passing the messages from telegram to you.", e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))

    # ---------------------------------- #

    async def _look_for_content(self, update: Update, context: CallbackContext, parent_event: event.Event):
        message: Message = update.effective_message
        content = []

        if message.photo or (message.document and message.document.mime_type and message.document.mime_type.startswith('image/')):
            image_list = await self._download_images_telegram(update, context, parent_event)
            if isinstance(image_list, list) and image_list:
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
                def sync_process(img_bytes):
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
                        
                    wrap = wrapper.ImageWrapper(id=message.id, chat_id=chat.id, x=new_width, y=new_height, image_bytes=img_bytes)
                    return wrap
                
                return await asyncio.to_thread(sync_process, img_bytes)
            
            images = await asyncio.gather(*[process_image(img_bytes) for img_bytes in file_bytes])

            return images
        
        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error='Failed to download image.', e=e, tb=tb, event_id=parent_event.event_id, chat_id=chat.id))