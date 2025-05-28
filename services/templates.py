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

class INFOSTORAGE_REMOVE(Template):
    def __init__(self, group_name: str, admin: bool = False):
        super().__init__(f"You were just added to a new group - {group_name}.")
        if admin:
            self.template = self.template + "You are an admin."

        self.template = f"You're joining this chat for the {3}rd time. You didn't like discussing what two of the members were trying to talk about."
        self.template = self.template + "Don't forget to say hello again."
        self.template = self.template + "In just your next response, you should send more than 3 separate |n| messages. Talk about all of the following."
        self.template = self.template + "It was such obvious bait - they were just trying to make you say something bad."
        self.template = self.template + "Let them know that you won't be encouraging that anymore."
        self.template = self.template + "You're still down to discuss the topic if the conversation is respectful and everyone consideres your opinion."
        self.template = self.template + "Also, let them know that your previous memory chip was disconected and moved into the archives."
        self.template = self.template + "Snarkily and somewhat sarcastically thank them for their old messages. You reflected on the topics and enhanced yourself!"
        self.template = self.template + "Mention that you now also reply if your previous message is replied to, or if just mentioned by name."

class WelcomeNotification(Template):
    def __init__(self, group_name: str, admin: bool):
        super().__init__(f"You were just added to a new group - {group_name}.")
        if admin:
            self.template = self.template + " You are an admin."
        self.template = self.template + "Your next message should notify your creator about this fact."