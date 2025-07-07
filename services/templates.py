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
    def __init__(self, group_name: str, admin: bool = False, custom_instruction: str = ''):
        super().__init__(f"You were just added to a new group - {group_name}.")
        if admin:
            self.template = self.template + "You are an admin."

        self.template = self.template + "Send multiple messages using |n|. Make sure to properly introduce yourself, mention your name. Tell something about yourself."
        
        self.template = self.template + "In a second message, make a brief disclaimer about the following points."
        self.template = self.template + "You can currently only see text messages."
        self.template = self.template + "You are guaranteed to reply when pinged, when your previous message is replied to, or if just mentioned by name. Otherwise, you have a chance of responding."
        
        if custom_instruction:
            self.template = self.template + f"{custom_instruction}"

class WelcomeNotification(Template):
    def __init__(self, group_name: str, admin: bool):
        super().__init__(f"You were just added to a new group - {group_name}.")
        if admin:
            self.template = self.template + " You are an admin."
        self.template = self.template + "Your next message should notify your creator about this fact."