# main webapp. 
# runs using FastAPI with async support
# IS NOT the entry point
# entry point is still mibo.py. 
# see how mibo.py runs and start the webapp from there

from core import ref
from events import event_bus

class WebApp:
    def __init__(self, bus: event_bus.EventBus, ref: ref.Ref, host: str, port: int, **kwargs):
        self.bus = bus
        self.ref = ref
        self.host = host
        self.port = port

    async def start(self):
        pass