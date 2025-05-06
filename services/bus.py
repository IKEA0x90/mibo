import asyncio

class EventBus:
    def __init__(self):
        self._listeners = {}

    def register(self, event_name: str, handler):
        self._listeners.setdefault(event_name, []).append(handler)

    async def emit(self, event_name: str, data):
        for handler in self._listeners.get(event_name, []):
            if asyncio.iscoroutinefunction(handler):
                asyncio.create_task(handler(data))
            else:
                handler(data)


# Handlers connected to PTB
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await bus.emit("command_start", update)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await bus.emit("message_text", update)

app = Application.builder().token("YOUR_BOT_TOKEN").build()

app.add_handler(CommandHandler("start", handle_start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

app.run_polling()
