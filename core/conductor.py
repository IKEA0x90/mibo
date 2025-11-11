import asyncio
import random
import sys
import datetime as dt

from io import BytesIO
from PIL import Image
from typing import Dict, List, cast
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
        
        # Media group buffering
        self._media_group_buffers: Dict[str, List[Update]] = {}
        self._media_group_tasks: Dict[str, asyncio.Task] = {}
        self._media_group_timeout = 1.0  # 1 second timeout for album completion

        self._register()

    def _register(self):
        self.bus.register(mibo_events.NewMessageArrived, self._capture_message)

    async def _capture_message(self, event: mibo_events.NewMessageArrived):
        '''
        Listens to new messages sent to chats and processes them into Wrappers.
        ''' 
        update: Update = event.update
        context: CallbackContext = event.context

        message: Message = update.effective_message
        if message and hasattr(message, 'media_group_id') and message.media_group_id:
            media_group_id = message.media_group_id
            
            # Add to buffer
            if media_group_id not in self._media_group_buffers:
                self._media_group_buffers[media_group_id] = []
            self._media_group_buffers[media_group_id].append(update)
            
            # If no task is running for this media group, start one
            if media_group_id not in self._media_group_tasks:
                self._media_group_tasks[media_group_id] = asyncio.create_task(
                    self._process_media_group(media_group_id, event)
                )
            return  # Don't process yet, wait for the complete album
        
        # Process single message immediately
        await self._process_single_message(update, context, event)

    async def _process_media_group(self, media_group_id: str, original_event: mibo_events.NewMessageArrived):
        '''
        Wait for media group completion, then process all messages in the group together.
        '''
        try:
            await asyncio.sleep(self._media_group_timeout)
            
            # Get all buffered messages for this media group
            album_updates = self._media_group_buffers.pop(media_group_id, [])
            self._media_group_tasks.pop(media_group_id, None)
            
            if not album_updates:
                return
                
            await self._process_album_messages(album_updates, original_event)
            
        except Exception as e:
            # Clean up on error
            self._media_group_buffers.pop(media_group_id, None)
            self._media_group_tasks.pop(media_group_id, None)
            _, _, tb = sys.exc_info()
            chat_id = album_updates[0].effective_chat.id if album_updates else None
            await self.bus.emit(system_events.ErrorEvent(
                error="Error processing media group", e=e, tb=tb, 
                event_id=original_event.event_id, chat_id=chat_id
            ))

    async def _process_album_messages(self, album_updates: List[Update], original_event: mibo_events.NewMessageArrived):
        '''
        Process all messages in an album together, handling shared and individual captions properly.
        '''
        if not album_updates:
            return
            
        primary_update = album_updates[0]
        context = original_event.context
        
        try:
            message_info = await self._extract_message_info(primary_update, original_event)
            if not message_info:
                return

            shared_texts = []
            individual_captions = []
            
            message_texts = []
            for update in album_updates:
                msg = update.effective_message
                text = msg.text or msg.caption or ''
                message_texts.append(text.strip() if text else '')
            
            text_counts = {}
            for text in message_texts:
                if text:
                    text_counts[text] = text_counts.get(text, 0) + 1
            
            # Separate shared vs individual content
            for i, text in enumerate(message_texts):
                if text:
                    if text_counts[text] > 1:
                        if text not in shared_texts:
                            shared_texts.append(text)
                    else:
                        individual_captions.append((i, text))

            album_group_id = album_updates[0].effective_message.media_group_id

            all_text = ' '.join(shared_texts + [caption for _, caption in individual_captions])
            ping = await self._determine_ping_status(
                message_info, all_text, context, original_event
            )

            # Create shared message wrapper for shared album caption
            wrappers = []
            if shared_texts:
                combined_shared_text = ' '.join(shared_texts)
                shared_message_wrapper = wrapper.MessageWrapper(
                    id=message_info['message_id'], 
                    chat_id=message_info['chat_id'], 
                    message=combined_shared_text, 
                    ping=ping, 
                    reply_id=message_info['reply_id'], 
                    quote=message_info['quote_text'],
                    datetime=message_info['datetime'], 
                    role=message_info['role'], 
                    user=message_info['username'],
                    group_id=album_group_id
                )
                wrappers.append(shared_message_wrapper)

            # Create individual caption wrappers for each unique image caption
            for img_index, caption in individual_captions:
                update = album_updates[img_index]
                caption_id = f"{update.effective_message.message_id}_caption"
                
                caption_wrapper = wrapper.MessageWrapper(
                    id=caption_id,
                    chat_id=message_info['chat_id'],
                    message=caption,
                    ping=ping,
                    reply_id=message_info['reply_id'],
                    quote=message_info['quote_text'],
                    datetime=message_info['datetime'],
                    role=message_info['role'],
                    user=message_info['username'],
                    group_id=album_group_id
                )
                wrappers.append(caption_wrapper)
            
            # Collect all images from all messages in the album
            all_content = []
            if context:
                for update in album_updates:
                    content = await self._look_for_content(update, context, original_event)
                    if content:
                        # Set the group_id for all images to link them to this album
                        for c in content:
                            c.group_id = album_group_id
                        all_content.extend(content)

                for c in all_content:
                    c.role = message_info['role']
                    c.user = message_info['username']
                    c.ping = ping
                    c.datetime = message_info['datetime']

            wrappers.extend(all_content)

            if not wrappers:
                raise ValueError("Wrapper list is somehow empty. This probably shouldn't happen.")
            
            await self._process_wrappers(
                wrappers, message_info, original_event.typing, original_event
            )

        except Exception as e:
            _, _, tb = sys.exc_info()
            chat_id = album_updates[0].effective_chat.id if album_updates else None
            await self.bus.emit(system_events.ErrorEvent(
                error="Something's wrong with processing album messages.", 
                e=e, tb=tb, event_id=original_event.event_id, chat_id=chat_id
            ))

    async def _process_single_message(self, update: Update, context: CallbackContext, event: mibo_events.NewMessageArrived):
        try:
            message_info = await self._extract_message_info(update, event)
            if not message_info:
                return

            message_text = message_info['message_text']

            ping = await self._determine_ping_status(message_info, message_text, context, event)

            message_wrapper = wrapper.MessageWrapper(
                id=message_info['message_id'], 
                chat_id=message_info['chat_id'], 
                message=message_text, 
                ping=ping, 
                reply_id=message_info['reply_id'], 
                quote=message_info['quote_text'],
                datetime=message_info['datetime'], 
                role=message_info['role'], 
                user=message_info['username']
            )
            
            content = []
            if context:
                content = await self._look_for_content(update, context, event)

                for c in content:
                    c.role = message_info['role']
                    c.user = message_info['username']
                    c.ping = ping
                    c.datetime = message_info['datetime']

            wrappers = ([message_wrapper] if message_wrapper.message else [])
            wrappers += content

            if not wrappers:
                raise ValueError("Wrapper list is somehow empty. This probably shouldn't happen.")
            
            # Process the message through the system
            await self._process_wrappers(wrappers, message_info, event.typing, event)

        except Exception as e:
            _, _, tb = sys.exc_info()
            chat_id = str(update.effective_chat.id) if update.effective_chat else None
            await self.bus.emit(system_events.ErrorEvent(
                error="Something's wrong with passing the messages from telegram to you.", 
                e=e, tb=tb, event_id=event.event_id, chat_id=chat_id
            ))

    async def _extract_message_info(self, update: Update, event: mibo_events.NewMessageArrived):
        '''
        Extract basic information from a message update.
        Returns a dictionary with message metadata or None if invalid.
        '''
        chat: Chat = update.effective_chat
        message: Message = update.effective_message

        if not chat or not message:
            return None

        user: User = message.from_user
        if not user:
            return None
        
        chat_id: str = str(chat.id)
        message_id: str = str(message.message_id)
        chat_name: str = chat.title or user.username or user.first_name or 'No chat name'

        if not chat_id or not message_id:
            return None

        chat_type = chat.type
        user_id = user.id
        username = user.username or user.first_name

        user_wrapper: wrapper.UserWrapper = await self.ref.get_user(user_id, username=username)

        system_message = hasattr(event, 'system')

        if system_message:
            role = 'system'
        else:
            role = 'assistant' if user.username == variables.Variables.USERNAME else 'user'

        message_text = message.text or message.caption or ''

        # Process reply information
        reply_message = message.reply_to_message
        reply_id = reply_message.message_id if reply_message else None

        quote = reply_message.quote if reply_message else None
        quote_text = quote.text if quote else None

        forward_origin = message.forward_origin

        datetime: dt.datetime = message.date.astimezone(dt.timezone.utc)

        # Process entities
        entities = message.parse_entities()
        caption_entities = message.parse_caption_entities()

        return {
            'chat_id': chat_id,
            'message_id': message_id,
            'chat_name': chat_name,
            'chat_type': chat_type,
            'user_id': user_id,
            'username': username,
            'user_wrapper': user_wrapper,
            'role': role,
            'message_text': message_text,
            'reply_id': reply_id,
            'reply_message': reply_message,
            'quote_text': quote_text,
            'forward_origin': forward_origin,
            'datetime': datetime,
            'entities': entities,
            'caption_entities': caption_entities,
            'system_message': system_message
        }

    async def _determine_ping_status(self, message_info: Dict, message_text: str, context: CallbackContext, event: mibo_events.NewMessageArrived):
        '''
        Determine if the bot should respond to this message (ping status).
        '''

        # Never ping on forwarded messages
        if message_info['forward_origin']:
            return False

        # Always ping in private chats or system messages
        if message_info['chat_type'] == Chat.PRIVATE or message_info['system_message']:
            return True

        # Check for mentions in entities
        entities = message_info['entities']
        caption_entities = message_info['caption_entities']
        
        if entities or caption_entities:
            for entity, value in {**entities, **caption_entities}.items():
                entity = cast(MessageEntity, entity)

                if entity.type == 'mention':
                    if value.startswith('@') and value[1:] == variables.Variables.USERNAME:
                        return True

                elif entity.type == 'url':
                    # special url processing
                    pass

        # Check if replying to bot
        reply_message = message_info['reply_message']
        if reply_message and context and (reply_message.from_user.id == context.bot.id):
            return True

        # Check if any assistant names are mentioned in text
        names = await self.ref.get_assistant_names(message_info['chat_id'])
        if any(name.lower() in message_text.lower() for name in names):
            return True

        return False

    async def _process_wrappers(self, wrappers: List[wrapper.Wrapper], message_info: Dict, typing_func, event: mibo_events.NewMessageArrived):
        '''
        Process wrappers through the system (add to database, check response conditions, emit events).
        '''
        chat_id = message_info['chat_id']
        chat_name = message_info['chat_name']
        user_wrapper = message_info['user_wrapper']

        wdw: window.Window = await self.ref.add_messages(chat_id, wrappers, chat_name=chat_name)
        request: Dict = await self.ref.get_request(chat_id)
        prompts: Dict[prompt_enum.PromptEnum, str] = await self.ref.get_prompts(chat_id)
        special_fields: Dict = await self.ref.get_special_fields(chat_id)

        special_fields['current_date_utc'] = dt.datetime.now(tz=dt.timezone.utc).strftime('%Y/%m/%d, %A')

        chance: int = await self.ref.get_chance(chat_id)
        random_chance = random.randint(1, 100)

        # Determine if any wrapper has ping=True
        has_ping = any(getattr(w, 'ping', False) for w in wrappers)
        
        respond = wdw.ready and ((random_chance <= chance) or has_ping)

        if respond:
            new_message_event = conductor_events.CompletionRequest(
                wdw=wdw, request=request, prompts=prompts, 
                special_fields=special_fields, typing=typing_func, 
                user=user_wrapper
            )
            await self.bus.emit(new_message_event)

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