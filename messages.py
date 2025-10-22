"""
Message classes for the chatbot application.

This module contains pure data models for messages used throughout the app.
By keeping them in a separate module, they remain stable across
Streamlit app reruns, avoiding isinstance comparison issues.

Rendering logic has been moved to ui_components.py for better separation of concerns.
"""
import streamlit as st
from abc import ABC, abstractmethod


class Message(ABC):
    """Abstract base class for all message types."""
    
    def __init__(self):
        pass

    @abstractmethod
    def to_input_messages(self):
        """Convert this message into a list of dicts suitable for the model API."""
        pass

    @abstractmethod
    def render(self, idx):
        """Render the message in the Streamlit app."""
        pass


class UserMessage(Message):
    """Represents a user message in the conversation."""
    
    def __init__(self, content: str):
        """
        Initialize a user message.
        
        Args:
            content: The text content of the user's message
        """
        super().__init__()
        self.content = content

    def to_input_messages(self):
        """Convert to API format."""
        return [{
            "role": "user",
            "content": self.content
        }]

    def render(self, _):
        """Render the user message in the UI."""
        from ui_components import render_message
        
        with st.chat_message("user"):
            st.markdown(self.content)


class AssistantResponse(Message):
    """Represents an assistant response, which may contain multiple messages."""
    
    def __init__(self, messages: list, request_id: str = None, user_token: str = None):
        """
        Initialize an assistant response.
        
        Args:
            messages: List of message dictionaries from the assistant
            request_id: Optional request ID for feedback tracking
            user_token: Optional user access token for user authorization
        """
        super().__init__()
        self.messages = messages
        # Request ID tracked to enable submitting feedback on assistant responses
        self.request_id = request_id
        self.user_token = user_token

    def to_input_messages(self):
        """Convert to API format."""
        return self.messages

    def render(self, idx: int):
        """Render the assistant response in the UI."""
        from ui_components import render_message, render_assistant_message_feedback
        
        with st.chat_message("assistant"):
            for msg in self.messages:
                render_message(msg)

            if self.request_id is not None:
                render_assistant_message_feedback(idx, self.request_id, self.user_token)
