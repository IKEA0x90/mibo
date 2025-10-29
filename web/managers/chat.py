# Allows to manage chats.
# Chat selector dropdown to choose which chat to manage. Chat names and IDs are shown. 
# Allows to change chat variables defined in ChatWrapper. 

# Shows a table of current chat window.py messages, in order. Only their text is displayed. Images are not rendered, but an |IMAGE| tag is shown when they are present.
# A selector box is present next to each message container. 
# One selector box selects all the messages (next to the table title).
# A button to clear the chat window is provided, which removes selected messages from it. Uses ref.py clear method. Does not delete the chat from the database, only window