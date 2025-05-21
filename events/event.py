import uuid

class Event:
    def __init__(self, name: str, **kwargs):
        self.event_id = str(uuid.uuid4().hex)
        self.name = name
        for key, value in kwargs.items():
            if key == 'event_id' or key == 'chat_id':
                value = str(value)
            setattr(self, key, value)

    def __eq__(self, value):
        if isinstance(value, Event):
            for attr in vars(self):
                if not hasattr(value, attr) or getattr(self, attr) != getattr(value, attr):
                    return False
            return True
        return False
    
    def __hash__(self):
        return self.event_id