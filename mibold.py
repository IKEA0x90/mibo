
from mibold import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from services import assistant, sql, window
        

    # ---------- handlers --------------------------------------------------
    def _register_handlers(self):
        self.app.add_handler(CommandHandler("debug", self.debug))
        self.app.add_handler(MessageHandler(filters.ALL, self.on_message))

    async def debug(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await context.bot.send_message(update.effective_chat.id, "Debug OK")

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            group_id = str(update.effective_chat.id)
            await self.db.ensure_group_exists(group_id)

            if not update.message:
                return
                
            # Get or create assistant for this chat
            chat_assistant = await self._get_chat_assistant(group_id)
            
            # Check if the message is a reply to the bot
            is_reply_to_bot = False
            if update.message.reply_to_message and hasattr(update.message.reply_to_message, 'from_user'):
                is_reply_to_bot = update.message.reply_to_message.from_user.is_bot
            
            # Determine the chance to respond based on whether it's a reply to the bot
            chance_to_run = 100 if is_reply_to_bot else 10  # Always respond to replies, 10% chance otherwise
            
            # Initialize message and add to window
            msg = await window.Message(update.message, group_id, self.db).initialize()
            
            # Get response from assistant
            reply = await chat_assistant.next_message(update.message, group_id, chance_to_run)
            
            # Deliver the response if there is one
            if reply:
                await self._deliver(update.effective_chat.id, reply, context)
        
        except Exception as e:
            # Handle any unexpected exceptions
            await self._handle_error(e, update.effective_chat.id, context)

    # ---------- assistant & output ---------------------------------------
    async def _get_chat_assistant(self, group_id):
        """Get or create an assistant for the specified chat"""
        if group_id not in self.chat_assistants:
            chat_assistant = assistant.Assistant("asst_oKibOhOv2uk4bE5Kn6lTFXRt", group_id)
            await chat_assistant.initialize()
            self.chat_assistants[group_id] = chat_assistant
        return self.chat_assistants[group_id]

    async def _handle_error(self, exception, chat_id, context):
        """Handle errors by creating a separate error-handling task"""
        try:
            print(f"Handling error in TelegramBot: {exception}")
            
            # Get or create the assistant for this chat
            chat_assistant = await self._get_chat_assistant(str(chat_id))
            
            # Use the assistant's error handler to generate a user-friendly message
            error_response = await chat_assistant.handle_exception(exception, str(chat_id))
            
            # Deliver the error response
            if error_response:
                await self._deliver(chat_id, error_response, context)
                
        except Exception as nested_error:
            # If error handling itself fails, send a simple message
            print(f"Error in error handler: {nested_error}")
            try:
                await context.bot.send_message(
                    chat_id, 
                    "I encountered an error and couldn't process your request. Please try again later."
                )
            except:
                pass

    async def _deliver(self, chat_id, resp, ctx):
        """Deliver the assistant's response to the user"""
        if not resp:
            return

        if resp.content.optional_text:
            await ctx.bot.send_message(chat_id, resp.content.optional_text)

        if resp.content.optional_image:
            try:
                with open(resp.content.optional_image.image_url, "rb") as f:
                    await ctx.bot.send_photo(chat_id, f)
            except Exception as e:
                print(f"image send error: {e}")
                # Try to inform the user about the image error
                await ctx.bot.send_message(chat_id, "I tried to send an image but encountered an error.")

        if resp.content.optional_sticker:
            try:
                await ctx.bot.send_sticker(
                    chat_id, resp.content.optional_sticker.sticker_pack
                )
            except Exception as e:
                print(f"sticker send error: {e}")
                # Optionally inform about sticker error if needed

    # ---------- lifecycle -------------------------------------------------
    async def bootstrap(self):
        """Init DB and anything else before Telegram starts polling."""
        await self.db.ensure_initialized()

    async def run(self):
        await self.bootstrap()

        # 1) create resources
        await self.app.initialize()
        await self.app.start()

        # 2) start polling (non‑blocking)
        await self.app.updater.start_polling()

        # 3) idle forever (or until you set the event)
        await asyncio.Event().wait()

        # 4) graceful shutdown (never reached unless you add a stop signal)
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()


async def main():
    bot = TelegramBot(TOKEN)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
