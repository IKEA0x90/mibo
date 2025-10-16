import openai
import datetime as dt
import random
import sys
import asyncio
import aiohttp

from typing import List, Dict
from io import BytesIO
from PIL import Image

from events import event_bus, conductor_events, assistant_events, system_events, event
from core import ref, window, wrapper
from services import prompt_enum, variables

class Assistant:
    def __init__(self, clients: Dict[str, openai.OpenAI], bus: event_bus.EventBus, referrer: ref.Ref, start_datetime: dt.datetime, **kwargs):

        self.clients: Dict[str, openai.OpenAI] = clients

        self.bus: event_bus.EventBus = bus
        self.ref: ref.Ref = referrer
        self.start_datetime: dt.datetime = start_datetime

        self._register()

    def _register(self):
        self.bus.register(conductor_events.CompletionRequest, self._trigger_completion)

    @staticmethod
    async def call_openai(sync_func, *args, **kwargs):
        '''
        Runs a synchronous OpenAI call in a thread pool, returns the result asynchronously.
        '''
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: sync_func(*args, **kwargs))

    async def _trigger_completion(self, event: conductor_events.CompletionRequest):
        '''
        Trigger a chat completion and return the response message. 
        '''
        wdw: window.Window = event.wdw
        request: Dict = event.request
        prompts: Dict[prompt_enum.PromptEnum, str] = event.prompts
        special_fields: Dict = event.special_fields

        current_date_utc = special_fields.get('current_date_utc', None)

        chat_id: str = wdw.chat_id
        model_provider = special_fields.get('model_provider', 'openai')

        user_messages: List[Dict]
        idx: Dict[str, int]
        user_messages, idx = await wdw.transform_messages()
        messages: List[Dict] = []

        base_prompt = prompts.get(prompt_enum.BasePrompt, '')
        messages.append({
            'role': 'system',
            'content': [{'type': 'text', 'text': f'{base_prompt}'}]
        })

        if current_date_utc:
            messages.append({
                'role': 'system',
                'content': [{'type': 'text', 'text': f'Current date UTC: {current_date_utc}'}]
            })

        if special_fields.get('disable_thinking'):
            messages.append({
                'role': 'system',
                'content': special_fields['disable_thinking_token']
            })

        for msg in user_messages:
            messages.append(msg)

        model = special_fields.get('model', 'gpt-4.1')
        request['safety_identifier'] = str(hash(chat_id))

        try:
            # start typing simulation
            typing = event.typing
            typing()

            client = self.clients.get(model_provider)
            response = await self.call_openai(client.chat.completions.create, messages=messages, model=model, extra_body=request)

            response_message = response.choices[0].message

            # For chat completions, content may be a list of blocks or a string
            content = response_message.content

            if isinstance(content, list):
                # Concatenate all text blocks for message text, collect images for content_list
                message_text = "".join([block.get('text', '') for block in content if block.get('type') == 'text'])
                images = [block for block in content if block.get('type') == 'image_url']

            else:
                message_text = content or ''
                images = [] # if it's not a list, no images

            if not message_text.strip() and not images:
                return
            
            # replace random stuff that I don't like and is easier to change here rather than in the prompt
            message_text = variables.Variables.replacers(message_text)
            
            if think_token := special_fields.get('think_token', ''):
                message_text = message_text.split(f'{think_token}', 1)[1]
                message_text = message_text.strip()

            wrapper_list = []

            message_list = variables.Variables.parse_text(message_text)

            for i, m in enumerate(message_list):  
                assistant_message = wrapper.MessageWrapper(
                    id=f'{str(response.id)}-{i}',
                    chat_id=chat_id, 
                    role='assistant', user=variables.Variables.USERNAME,
                    message=m, ping=False,
                    datetime=dt.datetime.now(tz=dt.timezone.utc)
                )

                wrapper_list.append(assistant_message)

            for i, img in enumerate(images):
                if 'image_url' in img:
                    incomplete_wrapper = wrapper.ImageWrapper(id=f'{str(response.id)}-{i}', chat_id=chat_id, x=0, y=0, role='assistant', user=variables.Variables.USERNAME)
                    image = await self._download_image_url(img['image_url'], incomplete_wrapper=incomplete_wrapper, parent_event=event)
                    wrapper_list.append(image)

            await self.ref.add_messages(chat_id, wrapper_list, False, idx=idx)

            response_event = assistant_events.AssistantResponse(messages=wrapper_list, event_id=event.event_id, typing=typing)
            await self.bus.emit(response_event)

        except Exception as e:
            _, _, tb = sys.exc_info()
            issue = system_events.ErrorEvent(error='Whoops! An unexpected error occurred.', e=e, tb=tb, event_id=event.event_id, chat_id=chat_id)
            await self.bus.emit(issue)

    async def _download_image_url(self, image_url: str, incomplete_wrapper: wrapper.ImageWrapper, parent_event: event.Event) -> wrapper.ImageWrapper:
        '''
        Downloads an image from a URL.
        Returns None if the download fails.
        '''
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=30) as response:

                    if response.status == 200:
                        image_bytes: bytes = await response.read()
                        incomplete_wrapper.image_bytes = image_bytes

                        def sync_process(img_bytes):
                            with Image.open(BytesIO(img_bytes)) as img:
                                width, height = img.size
                            return width, height

                        width, height = await asyncio.to_thread(sync_process, image_bytes)
                        incomplete_wrapper.x = width
                        incomplete_wrapper.y = height

                        return incomplete_wrapper

                    else:
                        issue = system_events.ErrorEvent(error='Error downloading an image.', e=None, tb=None, event_id=parent_event.event_id, chat_id=self.chat_id)
                        await self.bus.emit(issue)
                    
        except Exception as e:
            _, _, tb = sys.exc_info()
            issue = system_events.ErrorEvent(error='Error downloading an image.', e=e, tb=tb, event_id=parent_event.event_id, chat_id=self.chat_id)
            await self.bus.emit(issue)