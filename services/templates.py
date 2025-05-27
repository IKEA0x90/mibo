class Template:
    def __init__(self, template: str):
        self.template: str = template

    def insert(self, **kwargs) -> str:
        '''
        Inserts the given keyword arguments into the template string.
        '''
        try:
            return self.template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Missing placeholder for key: {e.args[0]}")
        
    def __str__(self) -> str:
        return self.template
        
class WelcomeMessage(Template):
    def __init__(self, group_name: str, admin: bool):
        super().__init__(f"You were just added to a new group - {group_name}.")
        if admin:
            self.template = self.template + "You are an admin."
        self.template = self.template + "Make sure to properly introduce yourself. Tell about what you can do."
        self.template = self.template + "Your current iteration allows you to respond to text messages. You are guaranteed to reply when pinged, otherwise you have a chance of responding."

class WelcomeNotification(Template):
    def __init__(self, group_name: str, admin: bool):
        super().__init__(f"You were just added to a new group - {group_name}.")
        if admin:
            self.template = self.template + " You are an admin."
        self.template = self.template + "Your next message should notify your creator about this fact."