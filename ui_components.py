"""
UI components module for rendering chat messages and UI elements.

This module contains all Streamlit-specific rendering logic, separated
from business logic and data models.
"""
import streamlit as st
import os


def render_message(msg: dict):
    """
    Render a single message in the chat interface.
    
    Args:
        msg: Message dictionary with 'role' and 'content' keys
    """
    if msg["role"] == "assistant":
        # Render content first if it exists
        if msg.get("content"):
            st.markdown(msg["content"])
        
        # Then render tool calls if they exist
        if "tool_calls" in msg and msg["tool_calls"]:
            for call in msg["tool_calls"]:
                fn_name = call["function"]["name"]
                args = call["function"]["arguments"]
                st.markdown(f"🛠️ Calling **`{fn_name}`** with:\n```json\n{args}\n```")
    elif msg["role"] == "tool":
        st.markdown("🧰 Tool Response:")
        st.code(msg["content"], language="json")


@st.fragment
def render_assistant_message_feedback(i: int, request_id: str, user_token: str = None):
    """
    Render feedback UI for assistant messages.
    
    Args:
        i: Index of the message in the history
        request_id: Request ID for submitting feedback
        user_token: Optional user access token for user authorization
    """
    from model_serving_utils import submit_feedback
    
    def save_feedback(index):
        serving_endpoint = os.getenv('SERVING_ENDPOINT')
        if serving_endpoint:
            submit_feedback(
                endpoint=serving_endpoint,
                request_id=request_id,
                rating=st.session_state[f"feedback_{index}"],
                user_token=user_token
            )
    
    st.feedback("thumbs", key=f"feedback_{i}", on_change=save_feedback, args=[i])


def render_chat_message(message_obj, idx: int):
    """
    Render a complete message object (UserMessage or AssistantResponse).
    
    Args:
        message_obj: Message object with render() method
        idx: Index of the message in the history
    """
    message_obj.render(idx)


def render_streaming_start():
    """Render the initial state for a streaming response."""
    response_area = st.empty()
    response_area.markdown("_Thinking..._")
    return response_area


def render_streaming_content(response_area, content: str):
    """
    Update the streaming response area with new content.
    
    Args:
        response_area: Streamlit element to update
        content: Content to display
    """
    response_area.markdown(content)


def render_streaming_messages(response_area, messages: list):
    """
    Render multiple messages in the streaming response area.
    
    Args:
        response_area: Streamlit element to update
        messages: List of message dictionaries
    """
    with response_area.container():
        for msg in messages:
            render_message(msg)


def render_streaming_error(response_area):
    """Render an error message in the streaming response area."""
    response_area.markdown("_Ran into an error. Retrying without streaming..._")

