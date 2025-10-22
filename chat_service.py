"""
Chat service module containing business logic for interacting with the chatbot.

This module handles:
- Query endpoint dispatching based on task type
- Streaming response handling
- Chunk reduction for agent responses
- Response processing and error handling
"""
import logging
from collections import OrderedDict
from model_serving_utils import (
    query_endpoint,
    query_endpoint_stream,
    _get_endpoint_task_type,
)
from messages import AssistantResponse

logger = logging.getLogger(__name__)


def reduce_chat_agent_chunks(chunks):
    """
    Reduce a list of ChatAgentChunk objects corresponding to a particular
    message into a single ChatAgentMessage
    """
    deltas = [chunk.delta for chunk in chunks]
    first_delta = deltas[0]
    result_msg = first_delta
    msg_contents = []
    
    # Accumulate tool calls properly
    tool_call_map = {}  # Map call_id to tool call for accumulation
    
    for delta in deltas:
        # Handle content
        if delta.content:
            msg_contents.append(delta.content)
            
        # Handle tool calls
        if hasattr(delta, 'tool_calls') and delta.tool_calls:
            for tool_call in delta.tool_calls:
                call_id = getattr(tool_call, 'id', None)
                tool_type = getattr(tool_call, 'type', "function")
                function_info = getattr(tool_call, 'function', None)
                if function_info:
                    func_name = getattr(function_info, 'name', "")
                    func_args = getattr(function_info, 'arguments', "")
                else:
                    func_name = ""
                    func_args = ""
                
                if call_id:
                    if call_id not in tool_call_map:
                        # New tool call
                        tool_call_map[call_id] = {
                            "id": call_id,
                            "type": tool_type,
                            "function": {
                                "name": func_name,
                                "arguments": func_args
                            }
                        }
                    else:
                        # Accumulate arguments for existing tool call
                        existing_args = tool_call_map[call_id]["function"]["arguments"]
                        tool_call_map[call_id]["function"]["arguments"] = existing_args + func_args

                        # Update function name if provided
                        if func_name:
                            tool_call_map[call_id]["function"]["name"] = func_name

        # Handle tool call IDs (for tool response messages)
        if hasattr(delta, 'tool_call_id') and delta.tool_call_id:
            result_msg = result_msg.model_copy(update={"tool_call_id": delta.tool_call_id})
    
    # Convert tool call map back to list
    if tool_call_map:
        accumulated_tool_calls = list(tool_call_map.values())
        result_msg = result_msg.model_copy(update={"tool_calls": accumulated_tool_calls})
    
    result_msg = result_msg.model_copy(update={"content": "".join(msg_contents)})
    return result_msg


class ChatService:
    """Service class for handling chat operations."""
    
    def __init__(self, endpoint_name: str, supports_feedback: bool = False):
        """
        Initialize the chat service.
        
        Args:
            endpoint_name: Name of the serving endpoint to query
            supports_feedback: Whether the endpoint supports feedback
        """
        self.endpoint_name = endpoint_name
        self.supports_feedback = supports_feedback
    
    def get_task_type(self, user_token: str = None) -> str:
        """
        Get the task type for the configured endpoint.
        
        Args:
            user_token: Optional user access token for user authorization
        
        Returns:
            Task type string
        """
        return _get_endpoint_task_type(self.endpoint_name, user_token)
    
    def query_and_process(self, task_type: str, input_messages: list, 
                         render_callback=None, user_token: str = None) -> AssistantResponse:
        """
        Query the endpoint and process the response based on task type.
        
        Args:
            task_type: The endpoint task type
            input_messages: List of messages to send to the endpoint
            render_callback: Optional callback function for rendering streaming responses.
                           Should accept (phase, data) where phase is 'start', 'chunk', or 'complete'
            user_token: Optional user access token for user authorization
        
        Returns:
            AssistantResponse containing the processed messages
        """
        if task_type == "agent/v1/responses":
            return self._query_responses_endpoint(input_messages, render_callback, user_token)
        elif task_type == "agent/v2/chat":
            return self._query_chat_agent_endpoint(input_messages, render_callback, user_token)
        else:  # chat/completions
            return self._query_chat_completions_endpoint(input_messages, render_callback, user_token)
    
    def _query_chat_completions_endpoint(self, input_messages: list, 
                                        render_callback=None, user_token: str = None) -> AssistantResponse:
        """Handle ChatCompletions streaming format."""
        if render_callback:
            render_callback('start', None)
        
        accumulated_content = ""
        request_id = None
        
        try:
            for chunk in query_endpoint_stream(
                endpoint_name=self.endpoint_name,
                messages=input_messages,
                return_traces=self.supports_feedback,
                user_token=user_token
            ):
                if "choices" in chunk and chunk["choices"]:
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        accumulated_content += content
                        if render_callback:
                            render_callback('chunk', accumulated_content)
                
                if "databricks_output" in chunk:
                    req_id = chunk["databricks_output"].get("databricks_request_id")
                    if req_id:
                        request_id = req_id
            
            messages = [{"role": "assistant", "content": accumulated_content}]
            if render_callback:
                render_callback('complete', messages)
            
            return AssistantResponse(
                messages=messages,
                request_id=request_id,
                user_token=user_token
            )
        except Exception as e:
            logger.exception("Error during streaming, falling back to non-streaming")
            if render_callback:
                render_callback('error', str(e))
            
            messages, request_id = query_endpoint(
                endpoint_name=self.endpoint_name,
                messages=input_messages,
                return_traces=self.supports_feedback
            )
            
            if render_callback:
                render_callback('complete', messages)
            
            return AssistantResponse(messages=messages, request_id=request_id)
    
    def _query_chat_agent_endpoint(self, input_messages: list, 
                                   render_callback=None, user_token: str = None) -> AssistantResponse:
        """Handle ChatAgent streaming format."""
        from mlflow.types.agent import ChatAgentChunk
        
        if render_callback:
            render_callback('start', None)
        
        message_buffers = OrderedDict()
        request_id = None
        
        try:
            for raw_chunk in query_endpoint_stream(
                endpoint_name=self.endpoint_name,
                messages=input_messages,
                return_traces=self.supports_feedback,
                user_token=user_token
            ):
                chunk = ChatAgentChunk.model_validate(raw_chunk)
                delta = chunk.delta
                message_id = delta.id

                req_id = raw_chunk.get("databricks_output", {}).get("databricks_request_id")
                if req_id:
                    request_id = req_id
                
                if message_id not in message_buffers:
                    message_buffers[message_id] = []
                
                message_buffers[message_id].append(chunk)
                
                # Reduce chunks and prepare for rendering
                partial_message = reduce_chat_agent_chunks(message_buffers[message_id])
                message_content = partial_message.model_dump_compat(exclude_none=True)
                
                if render_callback:
                    render_callback('chunk', {
                        'message_id': message_id,
                        'message': message_content,
                        'all_messages': [
                            reduce_chat_agent_chunks(chunks).model_dump_compat(exclude_none=True)
                            for chunks in message_buffers.values()
                        ]
                    })
            
            messages = [
                reduce_chat_agent_chunks(chunks).model_dump_compat(exclude_none=True)
                for chunks in message_buffers.values()
            ]
            
            if render_callback:
                render_callback('complete', messages)
            
            return AssistantResponse(
                messages=messages,
                request_id=request_id,
                user_token=user_token
            )
        except Exception as e:
            logger.exception("Error during streaming, falling back to non-streaming")
            if render_callback:
                render_callback('error', str(e))
            
            messages, request_id = query_endpoint(
                endpoint_name=self.endpoint_name,
                messages=input_messages,
                return_traces=self.supports_feedback,
                user_token=user_token
            )
            
            if render_callback:
                render_callback('complete', messages)
            
            return AssistantResponse(messages=messages, request_id=request_id)
    
    def _query_responses_endpoint(self, input_messages: list, 
                                 render_callback=None, user_token: str = None) -> AssistantResponse:
        """Handle ResponsesAgent streaming format using MLflow types."""
        from mlflow.types.responses import ResponsesAgentStreamEvent
        
        if render_callback:
            render_callback('start', None)
        
        all_messages = []
        request_id = None

        try:
            for raw_event in query_endpoint_stream(
                endpoint_name=self.endpoint_name,
                messages=input_messages,
                return_traces=self.supports_feedback,
                user_token=user_token
            ):
                # Extract databricks_output for request_id
                if "databricks_output" in raw_event:
                    req_id = raw_event["databricks_output"].get("databricks_request_id")
                    if req_id:
                        request_id = req_id
                
                # Parse using MLflow streaming event types
                if "type" in raw_event:
                    event = ResponsesAgentStreamEvent.model_validate(raw_event)
                    
                    if hasattr(event, 'item') and event.item:
                        item = event.item
                        
                        if item.get("type") == "message":
                            # Extract text content from message
                            content_parts = item.get("content", [])
                            for content_part in content_parts:
                                if content_part.get("type") == "output_text":
                                    text = content_part.get("text", "")
                                    if text:
                                        all_messages.append({
                                            "role": "assistant",
                                            "content": text
                                        })
                            
                        elif item.get("type") == "function_call":
                            # Tool call
                            call_id = item.get("call_id")
                            function_name = item.get("name")
                            arguments = item.get("arguments", "")
                            
                            all_messages.append({
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [{
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": function_name,
                                        "arguments": arguments
                                    }
                                }]
                            })
                            
                        elif item.get("type") == "function_call_output":
                            # Tool call output/result
                            call_id = item.get("call_id")
                            output = item.get("output", "")
                            
                            all_messages.append({
                                "role": "tool",
                                "content": output,
                                "tool_call_id": call_id
                            })
                
                # Update rendering
                if all_messages and render_callback:
                    render_callback('chunk', all_messages)

            if render_callback:
                render_callback('complete', all_messages)
            
            return AssistantResponse(messages=all_messages, request_id=request_id)
        except Exception as e:
            logger.exception("Error during streaming, falling back to non-streaming")
            if render_callback:
                render_callback('error', str(e))
            
            messages, request_id = query_endpoint(
                endpoint_name=self.endpoint_name,
                messages=input_messages,
                return_traces=self.supports_feedback,
                user_token=user_token
            )
            
            if render_callback:
                render_callback('complete', messages)
            
            return AssistantResponse(messages=messages, request_id=request_id)

