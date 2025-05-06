import json
import os
import openai
import random
import asyncio
import traceback

from wowsuchsmart_telegram import window

from mibold import Message as TelegramMessage
from services import image_generation

key = os.environ['OPENAI_API_KEY']
client = None  # Initialize client lazily

async def get_client():
    """Initialize and return the OpenAI client if needed"""
    global client
    if client is None:
        client = openai.AsyncOpenAI(api_key=key)
    return client

class Task:
    # wrapper for OpenAI assistant thread
    def __init__(self, client, assistant, context: list):
        self.client = client
        self.assistant = assistant

        self.status = 'in_progress'
        self.run = None
        self.thread = None
        self.context = context

    async def initialize(self):
        """Initialize the task with context"""
        try:
            processed_context = await window.Window.process_context(self.context)
            self.thread = await self.client.beta.threads.create(messages=processed_context)
            return self
        except Exception as e:
            print(f"Error initializing task: {e}")
            traceback.print_exc()
            raise

    async def start(self):
        try:
            if not self.thread:
                await self.initialize()

            await self._run()

            timeout = 30
            while (timeout):
                await asyncio.sleep(0.5)

                status = await self._get_status()
                if status == 'completed':
                    print(f'Completed run {self.thread.id}.')
                    break

                elif status == 'in_progress':
                    print(f'Run {self.thread.id} in progress. Timeout in {timeout} seconds')
                    timeout -= 1
                    continue

                elif status == 'requires_action':
                    await self._tool_call()

                else:
                    print(f"Unexpected status: {status}")
                    return None
                
            messages = await self.client.beta.threads.messages.list(thread_id=self.thread.id)
            message = messages.data[0]  # Get the latest message

            message_obj = window.MessageWrapper(
                role=message.role,
                user='wowsuchsmart',
                content=await self._parse_message_content(message.content)
            )

            return message_obj
        
        except Exception as e:
            print(f"Error starting task: {e}")
            traceback.print_exc()
            raise

    async def _get_status(self):
        try:
            if not self.run:
                return 'in_progress'
            
            print(f'Retrieving run {self.thread.id}...')
            self.run = await self.client.beta.threads.runs.retrieve(
                thread_id=self.thread.id,
                run_id=self.run.id
            )

            self.status = self.run.status
            return self.status
            
        except Exception as e:
            print(f"Error getting status: {e}")
            traceback.print_exc()
            return 'error'
        
    async def _run(self):
        try:
            print(f'Created run {self.thread.id}.')
            self.run = await self.client.beta.threads.runs.create(
                thread_id=self.thread.id,
                assistant_id=self.assistant.id,
                response_format={
               'type': 'json_schema',
               'json_schema': 
                  {
                    "name":"message", 
                    "schema": window.MessageWrapper.model_json_schema(),
                    'strict': True
                  }
             } 
            )
            return self.run
            
        except Exception as e:
            print(f"Error creating run: {e}")
            traceback.print_exc()
            raise
    
    async def _tool_call(self):      
        try:
            print(f'Run {self.run.id} requires action.')
            tools = self.run.required_action.submit_tool_outputs.tool_calls
            tool_outputs = [] 

            for tool in tools:
                name = tool.function.name
                args = json.loads(tool.function.arguments)

                if name == 'make_image':
                    await self._make_image(args, tool_outputs, tool)
                elif name == 'get_sticker':
                    await self._get_sticker(args, tool_outputs, tool)
                elif name == 'make_poll':
                    await self._make_poll(args, tool_outputs, tool)

            await self.client.beta.threads.runs.submit_tool_outputs(
                thread_id=self.thread.id,
                run_id=self.run.id,
                tool_outputs=tool_outputs
            )
        except Exception as e:
            print(f"Error handling tool call: {e}")
            traceback.print_exc()
            raise

    async def _make_image(self, args, tool_outputs, tool):
        try:
            print(f'Used make_image with {args.get("image_description")}')
            
            response = await image_generation.make_image(args.get('image_description'))
            image_path = await image_generation.save_image(response, f'/var/www/html/img/generated')
            
            print(f'Finished image generation for {args.get("image_description")}: {image_path}')

            tool_outputs.append({'tool_call_id': tool.id, 'output': image_path})
        except Exception as e:
            print(f"Error making image: {e}")
            traceback.print_exc()
            tool_outputs.append({'tool_call_id': tool.id, 'output': str(e)})

    async def _get_sticker(self, args, tool_outputs, tool):
        try:
            # Implement sticker functionality
            print(f"Get sticker called with args: {args}")
            tool_outputs.append({'tool_call_id': tool.id, 'output': 'Sticker not implemented yet'})
        except Exception as e:
            print(f"Error getting sticker: {e}")
            tool_outputs.append({'tool_call_id': tool.id, 'output': str(e)})

    async def _make_poll(self, args, tool_outputs, tool):
        try:
            # Implement poll functionality
            print(f"Make poll called with args: {args}")
            tool_outputs.append({'tool_call_id': tool.id, 'output': 'Poll not implemented yet'})
        except Exception as e:
            print(f"Error making poll: {e}")
            tool_outputs.append({'tool_call_id': tool.id, 'output': str(e)})
        
    async def _parse_message_content(self, content):
        """Parse the message content from the API response"""
        try:
            for item in content:
                if item.type == 'text':
                    return window.ContentWrapper(optional_text=item.text.value)
            return window.ContentWrapper()
        except Exception as e:
            print(f"Error parsing message content: {e}")
            return window.ContentWrapper(optional_text=f"Error parsing response: {e}")

class Assistant:
    def __init__(self, aid, gid):
        self.aid = aid    
        self.assistant = None
        self.window = window.Window(gid, image_dir='img/window')
        self.group_id = gid
        
    async def initialize(self):
        """Initialize the assistant by retrieving it from the API"""
        try:
            client = await get_client()
            self.assistant = await client.beta.assistants.retrieve(self.aid)
            
            # Initialize the database connection for the window
            if not self.window.db:
                from wowsuchsmart_telegram import sql
                self.window.db = sql.Database()
                await self.window.db.ensure_initialized()
                
            return self
            
        except Exception as e:
            print(f"Error initializing assistant: {e}")
            traceback.print_exc()
            raise
    
    async def next_message(self, message: TelegramMessage, gid, chance_to_run = 100) -> None:
        """Process the next message and optionally generate a response"""
        try:
            if not self.assistant:
                await self.initialize()
                
            message_obj = await window.Message(message, gid, self.window.db).initialize()
            self.window.add(message_obj)

            # Check if message is a reply to bot's message
            is_reply_to_bot = False
            reply_to_message_id = None
            
            if message.reply_to_message and hasattr(message.reply_to_message, 'from_user') and message.reply_to_message.from_user.is_bot:
                is_reply_to_bot = True
                # Get the original message ID that was replied to
                if hasattr(message.reply_to_message, 'message_id'):
                    reply_to_message_id = str(message.reply_to_message.message_id)

            # Determine whether to respond based on conditions
            should_respond = is_reply_to_bot or (random.randint(1, 100) <= chance_to_run)
            
            if should_respond:
                task = await self.create_task(message_obj.message_id, reply_to_message_id)
                wrapper = await self.run_task(task)
                return wrapper
            else:
                return None
                
        except Exception as e:
            print(f"Error processing next message: {e}")
            traceback.print_exc()
            # Create error response when exception occurs
            return await self.handle_exception(e, gid)
    
    async def create_task(self, message_id: str, response_id = None) -> Task:
        """Create a task with context for processing"""
        try:
            if not self.assistant:
                await self.initialize()
                
            client = await get_client()
            context = await self.window.get_context(message_id, response_id, memory_first=True)
            task = await Task(client, self.assistant, context).initialize()
            return task
            
        except Exception as e:
            print(f"Error creating task: {e}")
            traceback.print_exc()
            raise

    async def run_task(self, task):
        """Run a task and process the response"""
        try:
            response = await task.start()
            return response
            
        except Exception as e:
            print(f"Error running task: {e}")
            traceback.print_exc()
            return await self.handle_exception(e, self.group_id)
            
    async def handle_exception(self, exception: Exception, group_id: str):
        """Creates a separate task to parse and handle exceptions
        
        This method creates a new task with the exception information and returns
        a user-friendly error message to be sent to the chat where the error occurred.
        """
        try:
            print(f"Handling exception via dedicated handler: {exception}")
            
            # Create error parsing task prompt
            error_message = f'You just encountered an error: {exception}. ' \
                           f'Provide a short message explaining the issue. ' \
                           f'Never suggest solutions or include traceback information.'
            
            client = await get_client()
            
            # Create a simple message wrapper for the error
            response = await client.chat.completions.create(
                model='gpt-4.1',
                messages=[{"role": "system", "content": error_message}],
                temperature=0.7,
                max_tokens=150,
            )
            
            error_response_text = response.choices[0].message.content
            print(f'Error response: {error_response_text}')
            
            # Create message wrapper for the response
            wrapper = window.MessageWrapper(
                role='assistant',
                user='wowsuchsmart',
                content=window.ContentWrapper(optional_text=error_response_text),
                need_to_finish=False
            )
            
            return wrapper
            
        except Exception as e:
            # Fallback if error handler itself fails
            print(f"Error in exception handler: {e}")
            return window.MessageWrapper(
                role='assistant',
                user='wowsuchsmart',
                content=window.ContentWrapper(
                    optional_text="Meow... I encountered an unexpected error and couldn't process your request."
                ),
                need_to_finish=False
            )

    @staticmethod
    async def get_single_response(messages, temperature=1, max_tokens=600):
        """Get a single response from the OpenAI API"""
        try:
            print(f'Sending message: {messages}')
            client = await get_client()
            
            response = await client.chat.completions.create(
                model='gpt-4.1',
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            response_text = response.choices[0].message.content
            print(f'Response: {response_text}')
            
            wrapper = window.MessageWrapper(role='assistant', user='wowsuchsmart', content=window.ContentWrapper(optional_text=response_text), need_to_finish=False)
            return wrapper
            
        except Exception as e:
            print(f"I encountered an error: {e}")
            return f"I encountered an error: {e}"
            
    @staticmethod
    async def parse_message_content(content):
        """Parse the content from an API response into a ContentWrapper object"""
        try:
            wrapper = window.ContentWrapper()
            
            for item in content:
                if item.type == 'text':
                    wrapper.optional_text = item.text.value
                    
            return wrapper
            
        except Exception as e:
            print(f"Error parsing message content: {e}")
            return window.ContentWrapper(optional_text=f"Error parsing content: {e}")