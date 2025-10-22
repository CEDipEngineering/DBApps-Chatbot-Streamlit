"""
Databricks Agent Chatbot - Streamlit Application

A production-ready chatbot UI for interacting with Databricks AI agents
and foundation models through Model Serving endpoints.

This is the main entry point and handles only UI/frontend concerns.
Business logic is separated into chat_service.py.
"""
import logging
import os
import streamlit as st
from model_serving_utils import endpoint_supports_feedback
from messages import UserMessage
from chat_service import ChatService
from ui_components import (
    render_streaming_start,
    render_streaming_content,
    render_streaming_messages,
    render_streaming_error,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get serving endpoint from environment
SERVING_ENDPOINT = os.getenv('SERVING_ENDPOINT')
assert SERVING_ENDPOINT, \
    ("Unable to determine serving endpoint to use for chatbot app. If developing locally, "
     "set the SERVING_ENDPOINT environment variable to the name of your serving endpoint. If "
     "deploying to a Databricks app, include a serving endpoint resource named "
     "'serving_endpoint' with CAN_QUERY permissions, as described in "
     "https://docs.databricks.com/aws/en/generative-ai/agent-framework/chat-app#deploy-the-databricks-app")

# Check if endpoint supports feedback
ENDPOINT_SUPPORTS_FEEDBACK = endpoint_supports_feedback(SERVING_ENDPOINT)

# Initialize chat service
chat_service = ChatService(
    endpoint_name=SERVING_ENDPOINT,
    supports_feedback=ENDPOINT_SUPPORTS_FEEDBACK
)


# --- Initialize session state ---
if "history" not in st.session_state:
    st.session_state.history = []


# --- Page setup ---
st.title("🧱 Chatbot App")
st.write(f"A basic chatbot using your own serving endpoint.")
st.write(f"Endpoint name: `{SERVING_ENDPOINT}`")


# --- Render chat history ---
for i, element in enumerate(st.session_state.history):
    element.render(i)


# --- Handle streaming responses ---
def create_render_callback(task_type: str):
    """
    Create a callback function for rendering streaming responses.
    
    Args:
        task_type: The endpoint task type
        
    Returns:
        A callback function that handles rendering based on the task type
    """
    response_area = None
    
    def callback(phase: str, data):
        nonlocal response_area
        
        if phase == 'start':
            # Initialize the response area
            with st.chat_message("assistant"):
                response_area = render_streaming_start()
        
        elif phase == 'chunk':
            if response_area:
                response_area.empty()
                
                if task_type == "chat/completions":
                    # For chat completions, data is the accumulated content string
                    render_streaming_content(response_area, data)
                
                elif task_type == "agent/v2/chat":
                    # For chat agent, data is a dict with all_messages
                    if isinstance(data, dict) and 'all_messages' in data:
                        render_streaming_messages(response_area, data['all_messages'])
                
                elif task_type == "agent/v1/responses":
                    # For responses agent, data is the list of all messages
                    render_streaming_messages(response_area, data)
        
        elif phase == 'error':
            # Show error message and prepare for fallback
            if response_area:
                render_streaming_error(response_area)
        
        elif phase == 'complete':
            # Finalize rendering
            if response_area:
                response_area.empty()
                render_streaming_messages(response_area, data)
    
    return callback


# --- Chat input ---
prompt = st.chat_input("Ask a question")
if prompt:
    # Retrieve user access token from Streamlit headers for user authorization
    # This allows the app to act on behalf of the user with their Unity Catalog permissions
    user_token = st.context.headers.get('x-forwarded-access-token')
    
    # Get the task type for this endpoint
    task_type = chat_service.get_task_type(user_token=user_token)
    
    # Add user message to chat history
    user_msg = UserMessage(content=prompt)
    st.session_state.history.append(user_msg)
    user_msg.render(len(st.session_state.history) - 1)

    # Convert history to standard chat message format
    input_messages = [
        msg 
        for elem in st.session_state.history 
        for msg in elem.to_input_messages()
    ]
    
    # Create a render callback for streaming
    render_callback = create_render_callback(task_type)
    
    # Query the endpoint and get the response using user authorization
    assistant_response = chat_service.query_and_process(
        task_type=task_type,
        input_messages=input_messages,
        render_callback=render_callback,
        user_token=user_token
    )
    
    # Add assistant response to history
    st.session_state.history.append(assistant_response)
