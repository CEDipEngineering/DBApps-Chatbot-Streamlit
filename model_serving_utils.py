from mlflow.deployments import get_deploy_client
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config
import json
import uuid
import os
import requests

import logging

logging.basicConfig(
    format="%(levelname)s [%(asctime)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.DEBUG
)

def _get_deploy_client_with_token(user_token: str = None):
    """
    Get a deployment client configured with user or app credentials.
    
    Args:
        user_token: Optional user access token for user authorization.
                   If None, uses app service principal credentials.
    
    Returns:
        Configured MLflow deployment client
    """
    # Note: MLflow deployment client doesn't properly support passing user tokens
    # For user authorization, we use WorkspaceClient API directly in the query functions
    return get_deploy_client("databricks")

def _get_workspace_client_with_token(user_token: str = None):
    """
    Get a workspace client configured with user or app credentials.
    
    Args:
        user_token: Optional user access token for user authorization.
                   If None, uses app service principal credentials.
    
    Returns:
        Configured WorkspaceClient
    """
    if user_token:
        # User authorization: use the user's access token
        # Explicitly set auth_type to avoid conflicts with service principal env vars
        # Create config with explicit auth type to override environment variables
        cfg = Config(
            host=os.getenv("DATABRICKS_HOST"),
            token=user_token,
            auth_type='pat'  # Explicitly use personal access token auth
        )
        return WorkspaceClient(config=cfg)
    else:
        # App authorization: use default SDK authentication (service principal)
        return WorkspaceClient()

def _get_endpoint_task_type(endpoint_name: str, user_token: str = None) -> str:
    """
    Get the task type of a serving endpoint.
    
    Args:
        endpoint_name: Name of the serving endpoint
        user_token: Optional user access token
    
    Returns:
        Task type string
    """
    try:
        w = _get_workspace_client_with_token(user_token)
        ep = w.serving_endpoints.get(endpoint_name)
        return ep.task if ep.task else "chat/completions"
    except Exception:
        return "chat/completions"

def _convert_to_responses_format(messages):
    """Convert chat messages to ResponsesAgent API format."""
    input_messages = []
    for msg in messages:
        if msg["role"] == "user":
            input_messages.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            # Handle assistant messages with tool calls
            if msg.get("tool_calls"):
                # Add function calls
                for tool_call in msg["tool_calls"]:
                    input_messages.append({
                        "type": "function_call",
                        "id": tool_call["id"],
                        "call_id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "arguments": tool_call["function"]["arguments"]
                    })
                # Add assistant message if it has content
                if msg.get("content"):
                    input_messages.append({
                        "type": "message",
                        "id": msg.get("id", str(uuid.uuid4())),
                        "content": [{"type": "output_text", "text": msg["content"]}],
                        "role": "assistant"
                    })
            else:
                # Regular assistant message
                input_messages.append({
                    "type": "message",
                    "id": msg.get("id", str(uuid.uuid4())),
                    "content": [{"type": "output_text", "text": msg["content"]}],
                    "role": "assistant"
                })
        elif msg["role"] == "tool":
            input_messages.append({
                "type": "function_call_output",
                "call_id": msg.get("tool_call_id"),
                "output": msg["content"]
            })
    return input_messages

def _throw_unexpected_endpoint_format():
    raise Exception("This app can only run against ChatModel, ChatAgent, or ResponsesAgent endpoints")

def query_endpoint_stream(endpoint_name: str, messages: list[dict[str, str]], 
                         return_traces: bool, user_token: str = None):
    """
    Query endpoint with streaming, using user or app credentials.
    
    Args:
        endpoint_name: Name of the serving endpoint
        messages: List of messages to send
        return_traces: Whether to request traces
        user_token: Optional user access token for user authorization
    """
    task_type = _get_endpoint_task_type(endpoint_name, user_token)
    
    if task_type == "agent/v1/responses":
        return _query_responses_endpoint_stream(endpoint_name, messages, return_traces, user_token)
    else:
        return _query_chat_endpoint_stream(endpoint_name, messages, return_traces, user_token)

def _query_chat_endpoint_stream(endpoint_name: str, messages: list[dict[str, str]], 
                                return_traces: bool, user_token: str = None):
    """
    Invoke an endpoint that implements either chat completions or ChatAgent and stream the response.
    
    Args:
        endpoint_name: Name of the serving endpoint
        messages: List of messages to send
        return_traces: Whether to request traces
        user_token: Optional user access token for user authorization
    """
    # Prepare input payload
    inputs = {
        "messages": messages,
    }
    if return_traces:
        inputs["databricks_options"] = {"return_trace": True}

    if user_token:
        # User authorization: use WorkspaceClient with user token for proper auth
        w = _get_workspace_client_with_token(user_token)
        
        # Get the host from workspace client
        host = w.config.host.rstrip('/')
        
        # Make streaming request directly
        response = requests.post(
            f"{host}/serving-endpoints/{endpoint_name}/invocations",
            json=inputs,
            headers={
                "Authorization": f"Bearer {user_token}",
                "Content-Type": "application/json"
            },
            stream=True
        )
        response.raise_for_status()
        
        # Parse streaming response
        for line in response.iter_lines():
            if line:
                # Remove "data: " prefix if present
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    line_str = line_str[6:]
                if line_str.strip():
                    try:
                        chunk = json.loads(line_str)
                        if "choices" in chunk:
                            yield chunk
                        elif "delta" in chunk:
                            yield chunk
                    except json.JSONDecodeError:
                        continue
    else:
        # App authorization: use MLflow deployment client
        client = _get_deploy_client_with_token(user_token)
        for chunk in client.predict_stream(endpoint=endpoint_name, inputs=inputs):
            if "choices" in chunk:
                yield chunk
            elif "delta" in chunk:
                yield chunk
            else:
                _throw_unexpected_endpoint_format()

def _query_responses_endpoint_stream(endpoint_name: str, messages: list[dict[str, str]], 
                                     return_traces: bool, user_token: str = None):
    """
    Stream responses from agent/v1/responses endpoints using MLflow deployments client.
    
    Args:
        endpoint_name: Name of the serving endpoint
        messages: List of messages to send
        return_traces: Whether to request traces
        user_token: Optional user access token for user authorization
    """
    input_messages = _convert_to_responses_format(messages)
    
    # Prepare input payload for ResponsesAgent
    inputs = {
        "input": input_messages,
        "context": {},
        "stream": True
    }
    if return_traces:
        inputs["databricks_options"] = {"return_trace": True}

    if user_token:
        # User authorization: use WorkspaceClient API directly
        w = _get_workspace_client_with_token(user_token)
        
        # Use workspace client's API client for proper authentication
        for event_data in w.api_client.do(
            method='POST',
            path=f"/serving-endpoints/{endpoint_name}/invocations",
            body=inputs,
            headers={"Content-Type": "application/json"},
            stream=True
        ):
            yield event_data
    else:
        # App authorization: use MLflow deployment client
        client = _get_deploy_client_with_token(user_token)
        for event_data in client.predict_stream(endpoint=endpoint_name, inputs=inputs):
            yield event_data

def query_endpoint(endpoint_name, messages, return_traces, user_token: str = None):
    """
    Query an endpoint, returning the string message content and request ID for feedback.
    
    Args:
        endpoint_name: Name of the serving endpoint
        messages: List of messages to send
        return_traces: Whether to request traces
        user_token: Optional user access token for user authorization
    
    Returns:
        Tuple of (messages, request_id)
    """
    task_type = _get_endpoint_task_type(endpoint_name, user_token)
    
    if task_type == "agent/v1/responses":
        return _query_responses_endpoint(endpoint_name, messages, return_traces, user_token)
    else:
        return _query_chat_endpoint(endpoint_name, messages, return_traces, user_token)

def _query_chat_endpoint(endpoint_name, messages, return_traces, user_token: str = None):
    """
    Calls a model serving endpoint with chat/completions format.
    
    Args:
        endpoint_name: Name of the serving endpoint
        messages: List of messages to send
        return_traces: Whether to request traces
        user_token: Optional user access token for user authorization
    
    Returns:
        Tuple of (messages, request_id)
    """
    inputs = {'messages': messages}
    if return_traces:
        inputs['databricks_options'] = {'return_trace': True}
    
    if user_token:
        # User authorization: use WorkspaceClient API directly for proper auth
        w = _get_workspace_client_with_token(user_token)
        res = w.api_client.do(
            method='POST',
            path=f"/serving-endpoints/{endpoint_name}/invocations",
            body=inputs,
            headers={"Content-Type": "application/json"}
        )
    else:
        # App authorization: use MLflow deployment client
        client = _get_deploy_client_with_token(user_token)
        res = client.predict(
            endpoint=endpoint_name,
            inputs=inputs,
        )
    
    request_id = res.get("databricks_output", {}).get("databricks_request_id")
    if "messages" in res:
        return res["messages"], request_id
    elif "choices" in res:
        choice_message = res["choices"][0]["message"]
        choice_content = choice_message.get("content")
        
        # Case 1: The content is a list of structured objects
        if isinstance(choice_content, list):
            combined_content = "".join([part.get("text", "") for part in choice_content if part.get("type") == "text"])
            reformatted_message = {
                "role": choice_message.get("role"),
                "content": combined_content
            }
            return [reformatted_message], request_id
        
        # Case 2: The content is a simple string
        elif isinstance(choice_content, str):
            return [choice_message], request_id

    _throw_unexpected_endpoint_format()

def _query_responses_endpoint(endpoint_name, messages, return_traces, user_token: str = None):
    """
    Query agent/v1/responses endpoints using MLflow deployments client.
    
    Args:
        endpoint_name: Name of the serving endpoint
        messages: List of messages to send
        return_traces: Whether to request traces
        user_token: Optional user access token for user authorization
    
    Returns:
        Tuple of (messages, request_id)
    """
    input_messages = _convert_to_responses_format(messages)
    
    # Prepare input payload for ResponsesAgent
    inputs = {
        "input": input_messages,
        "context": {}
    }
    if return_traces:
        inputs["databricks_options"] = {"return_trace": True}
    
    # Make the prediction call
    if user_token:
        # User authorization: use WorkspaceClient API directly
        w = _get_workspace_client_with_token(user_token)
        response = w.api_client.do(
            method='POST',
            path=f"/serving-endpoints/{endpoint_name}/invocations",
            body=inputs,
            headers={"Content-Type": "application/json"}
        )
    else:
        # App authorization: use MLflow deployment client
        client = _get_deploy_client_with_token(user_token)
        response = client.predict(endpoint=endpoint_name, inputs=inputs)
    
    # Extract messages from the response
    result_messages = []
    request_id = response.get("databricks_output", {}).get("databricks_request_id")
    
    # Process the output items from ResponsesAgent response
    output_items = response.get("output", [])
    
    for item in output_items:
        item_type = item.get("type")
        
        if item_type == "message":
            # Extract text content from message
            text_content = ""
            content_parts = item.get("content", [])
            
            for content_part in content_parts:
                if content_part.get("type") == "output_text":
                    text_content += content_part.get("text", "")
            
            if text_content:
                result_messages.append({
                    "role": "assistant",
                    "content": text_content
                })
                
        elif item_type == "function_call":
            # Handle function calls
            call_id = item.get("call_id")
            function_name = item.get("name")
            arguments = item.get("arguments", "")
            
            tool_calls = [{
                "id": call_id,
                "type": "function", 
                "function": {
                    "name": function_name,
                    "arguments": arguments
                }
            }]
            result_messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": tool_calls
            })
            
        elif item_type == "function_call_output":
            # Handle function call output/result
            call_id = item.get("call_id")
            output_content = item.get("output", "")
            
            result_messages.append({
                "role": "tool",
                "content": output_content,
                "tool_call_id": call_id
            })
    
    return result_messages or [{"role": "assistant", "content": "No response found"}], request_id

def submit_feedback(endpoint, request_id, rating, user_token: str = None):
    """
    Submit feedback to the agent.
    
    Args:
        endpoint: Name of the serving endpoint
        request_id: Request ID to associate feedback with
        rating: Rating value (1 for positive, 0 for negative)
        user_token: Optional user access token for user authorization
    """
    rating_string = "positive" if rating == 1 else "negative"
    text_assessments = [] if rating is None else [{
        "ratings": {
            "answer_correct": {"value": rating_string},
        },
        "free_text_comment": None
    }]

    proxy_payload = {
        "dataframe_records": [
            {
                "source": json.dumps({
                    "id": "e2e-chatbot-app",
                    "type": "human"
                }),
                "request_id": request_id,
                "text_assessments": json.dumps(text_assessments),
                "retrieval_assessments": json.dumps([]),
            }
        ]
    }
    w = _get_workspace_client_with_token(user_token)
    return w.api_client.do(
        method='POST',
        path=f"/serving-endpoints/{endpoint}/served-models/feedback/invocations",
        body=proxy_payload,
    )


def endpoint_supports_feedback(endpoint_name, user_token: str = None):
    """
    Check if an endpoint supports feedback.
    
    Args:
        endpoint_name: Name of the serving endpoint
        user_token: Optional user access token for user authorization
    
    Returns:
        True if endpoint supports feedback, False otherwise
    """
    w = _get_workspace_client_with_token(user_token)
    endpoint = w.serving_endpoints.get(endpoint_name)
    return "feedback" in [entity.name for entity in endpoint.config.served_entities]
