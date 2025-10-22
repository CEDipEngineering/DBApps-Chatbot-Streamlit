# Databricks Agent Chatbot - Streamlit App

A production-ready Streamlit chatbot application for interacting with Databricks AI agents and foundation models through Model Serving endpoints. This app provides a customizable chat UI with streaming responses, tool call visualization, and user feedback collection.

## Overview

This application is based on the [official Databricks Agent Framework documentation](https://docs.databricks.com/en/generative-ai/agent-framework/chat-app.html) and provides a full-featured chat interface that can be deployed as a Databricks App.

### Key Features

- **🔐 User Authorization**: Uses user credentials to respect individual Unity Catalog permissions, including row-level filters and column masks
  
- **🎯 Multi-Endpoint Support**: Works with three types of serving endpoints:
  - Chat Completions endpoints (foundation models)
  - ChatAgent endpoints (agent/v2/chat)
  - ResponsesAgent endpoints (agent/v1/responses)
  
- **⚡ Streaming Responses**: Real-time streaming of agent responses for better user experience

- **🛠️ Tool Call Visualization**: Automatically renders tool calls and their results when agents use tools

- **👍 User Feedback**: Collects user feedback (thumbs up/down) on agent responses via the feedback API (requires endpoint to have feedback entity configured)

- **🔄 Automatic Fallback**: Falls back to non-streaming mode if streaming encounters errors

## Architecture

### Project Structure

```
.
├── app.py                    # Main Streamlit application (UI/Frontend)
├── app.yaml                  # Databricks App configuration
├── chat_service.py           # Chat business logic and service layer
├── messages.py               # Message data models
├── model_serving_utils.py    # Low-level API client for endpoints
├── ui_components.py          # UI rendering components
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

### How It Works

1. **User Authorization**: When a user interacts with the app, their access token is retrieved from Streamlit headers
2. **User Input**: Users type messages in the Streamlit chat input
3. **History Management**: The app maintains conversation history in Streamlit session state
4. **Endpoint Detection**: Automatically detects the endpoint's task type using user credentials
5. **Query with User Permissions**: Sends the conversation history to the serving endpoint with the user's access token, ensuring Unity Catalog permissions are enforced
6. **Streaming Query**: Streams responses in real-time with user authorization
7. **Response Rendering**: Parses and displays responses in real-time, including:
   - Text content
   - Tool calls (function names and arguments)
   - Tool responses
8. **Feedback Collection** (optional): If the endpoint supports feedback, users can rate responses with thumbs up/down using their credentials

### Architecture Layers

The application follows a clean separation of concerns with distinct layers:

#### **Frontend Layer**

**`app.py`** - Main application entry point (UI only):
- Initializes the Streamlit UI and page layout
- Retrieves user access token from Streamlit headers for user authorization
- Manages chat history using `st.session_state`
- Handles user input through Streamlit components
- Coordinates between the chat service and UI components
- Creates render callbacks for streaming responses
- Passes user token through to all service calls

**`ui_components.py`** - UI rendering components:
- `render_message()`: Renders individual messages with proper formatting
- `render_assistant_message_feedback()`: Streamlit fragment for feedback UI
- `render_streaming_start()`: Initializes streaming response display
- `render_streaming_content()`: Updates streaming content
- `render_streaming_messages()`: Renders multiple messages during streaming
- `render_streaming_error()`: Displays error messages

#### **Business Logic Layer**

**`chat_service.py`** - Chat business logic:
- `ChatService`: Main service class for chat operations
  - `query_and_process()`: Dispatches to appropriate handler based on task type
  - `_query_chat_completions_endpoint()`: Handles foundation model endpoints
  - `_query_chat_agent_endpoint()`: Handles ChatAgent (agent/v2/chat) endpoints
  - `_query_responses_endpoint()`: Handles ResponsesAgent (agent/v1/responses) endpoints
- `reduce_chat_agent_chunks()`: Accumulates streaming chunks into complete messages
- Manages streaming callbacks and error handling
- Falls back to non-streaming if errors occur

#### **Data Layer**

**`messages.py`** - Message data models:
- `Message`: Abstract base class for all message types
- `UserMessage`: Represents user input messages
- `AssistantResponse`: Represents agent responses (may contain multiple messages)
- All classes include `to_input_messages()` for API format conversion
- Minimal rendering logic (delegates to ui_components)

#### **API Client Layer**

**`model_serving_utils.py`** - Low-level API client:
- `_get_deploy_client_with_token()`: Creates deployment client with user or app credentials
- `_get_workspace_client_with_token()`: Creates workspace client with user or app credentials
- `_get_endpoint_task_type()`: Determines the endpoint's task type (supports user token)
- `query_endpoint_stream()`: Routes to appropriate streaming handler with user authorization
- `_query_chat_endpoint_stream()`: Streams from chat/completions or ChatAgent endpoints
- `_query_responses_endpoint_stream()`: Streams from ResponsesAgent endpoints
- `query_endpoint()`: Non-streaming fallback for all endpoint types
- `_convert_to_responses_format()`: Converts chat messages to ResponsesAgent API format
- `submit_feedback()`: Submits user feedback with user authorization
- `endpoint_supports_feedback()`: Checks if endpoint has feedback capability enabled

#### `app.yaml`
Databricks App configuration that defines:
- **Command**: How to run the Streamlit app (`streamlit run app.py`)
- **User Authorization Scopes**: Defines what the app can access on behalf of users (`sql`, `genai.genie`)
- **Environment variables**: Configuration like disabling Streamlit telemetry
- **Resource reference**: The `SERVING_ENDPOINT` environment variable uses `valueFrom: "serving-endpoint"` 

**Important:** The `valueFrom: "serving-endpoint"` in `app.yaml` is a **reference** to a resource that you configure separately when creating the app. The actual serving endpoint name and permissions are set via the `databricks apps create` command, not in this file. The resource must be:
- Named `"serving-endpoint"` (to match the `valueFrom` reference)
- Configured with your actual serving endpoint name
- Granted `CAN_QUERY` permission

**Example of the connection:**

In `app.yaml`:
```yaml
env:
  - name: "SERVING_ENDPOINT"
    valueFrom: "serving-endpoint"  # References a resource by name
```

In your app creation command:
```bash
databricks apps create --json '{
  "resources": [
    {
      "name": "serving-endpoint",  # This name matches the valueFrom above
      "serving_endpoint": {
        "name": "my-actual-endpoint-name",  # Your real endpoint name
        "permission": "CAN_QUERY"
      }
    }
  ]
}'
```

At runtime, the `SERVING_ENDPOINT` environment variable will be set to `"my-actual-endpoint-name"`.

**Why use resources instead of hardcoding?**

According to the [Databricks Apps Resources documentation](https://docs.databricks.com/en/dev-tools/databricks-apps/resources.html), you should avoid hardcoding resource IDs to keep apps portable and secure. Using resources:
- Makes your app portable across environments (dev, staging, production)
- Allows you to change the serving endpoint without modifying code
- Provides security through the app's service principal rather than hardcoded credentials
- Enables proper permission management at the platform level

## Requirements

### For the Databricks Endpoint

You must have one of the following deployed in your Databricks workspace:

1. **Custom Agent**: Deployed using `agents.deploy()` (must use current schema, not legacy)
2. **Agent Bricks**: Such as Knowledge Assistant or Multi-Agent Supervisor
3. **Foundation Model**: Any Mosaic AI Model Serving foundation model with the **Chat** task type

> **Note**: Agents deployed using legacy schemas are not supported.

> **Feedback Feature**: The user feedback feature (thumbs up/down) is optional and only works with endpoints that have a "feedback" served entity configured. The app will work normally without this feature - you just won't see feedback buttons.

### For Local Development

- **Python**: 3.11 or above
- **Databricks CLI**: Latest version
- **Databricks Personal Access Token**: For authentication
- **Access**: CAN_QUERY permission on the serving endpoint

## Setup Instructions

### 1. Local Development

#### Step 1: Clone and Install Dependencies

```bash
# Navigate to the project directory
cd /path/to/DBApps-Chatbot-Streamlit

# Install required Python packages
pip install -r requirements.txt
```

#### Step 2: Configure Databricks Authentication

Generate a personal access token in your Databricks workspace:
1. Go to **Settings** → **Developer** → **Access tokens**
2. Click **Generate new token**
3. Save the token securely

Configure the Databricks CLI:
```bash
databricks configure
```

When prompted, provide:
- **Databricks Host**: Your workspace URL (e.g., `https://your-workspace.cloud.databricks.com`)
- **Token**: Your personal access token

#### Step 3: Set Environment Variables

```bash
# Set the serving endpoint name
export SERVING_ENDPOINT=your-serving-endpoint-name
```

To find your serving endpoint name:
1. Go to your Databricks workspace
2. Navigate to **Serving** in the left sidebar
3. Copy the name of your deployed endpoint

#### Step 4: Run Locally

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`.

### 2. Deploy to Databricks

Deploying as a Databricks App allows you to share the chatbot with other users in your workspace.

You can deploy using either the **Databricks UI** (recommended for most users) or the **CLI** (for automation).

#### Option A: Deploy via Databricks UI (Recommended)

This is the easiest method and provides a visual interface for configuration.

**Prerequisites:**
- Your serving endpoint must already exist
- You must have `CAN MANAGE` permission on both the serving endpoint and the app you're creating

**Step 1: Create the App in the UI**

1. Go to your Databricks workspace
2. Click **Apps** in the left sidebar
3. Click **Create app**
4. Enter an app name (e.g., `my-agent-chatbot`)
5. In the **App resources** section, click **+ Add resource**
6. Select **Serving endpoint** as the resource type
7. Choose your deployed serving endpoint from the dropdown
8. Set permission to **CAN_QUERY**
9. Set the resource key to `serving-endpoint` (this must match the `valueFrom` value in `app.yaml`)
10. Click **Create**

> **Note**: The resource key `serving-endpoint` is critical - it must match the `valueFrom: "serving-endpoint"` value in your `app.yaml` file.

**Step 2: Upload Your Code**

From your local project directory:

```bash
# Get your Databricks username
DATABRICKS_USERNAME=$(databricks current-user me | jq -r .userName)

# Sync the source code to Databricks
databricks sync . "/Users/$DATABRICKS_USERNAME/e2e-chatbot-app"
```

**Step 3: Deploy the App**

1. In the Apps UI, find your app
2. Click on it to open the app details
3. In the **Source code path** field, enter: `/Workspace/Users/your-username/e2e-chatbot-app`
4. Click **Deploy**

For detailed instructions, see the [Databricks Apps Resources documentation](https://docs.databricks.com/en/dev-tools/databricks-apps/resources.html).

#### Option B: Deploy via CLI

**Step 1: Create the Databricks App**

Run the following command (ensure `SERVING_ENDPOINT` is still set from local development, or replace `$SERVING_ENDPOINT` with your endpoint name):

```bash
databricks apps create --json '{
  "name": "my-agent-chatbot",
  "resources": [
    {
      "name": "serving-endpoint",
      "serving_endpoint": {
        "name": "'"$SERVING_ENDPOINT"'",
        "permission": "CAN_QUERY"
      }
    }
  ]
}'
```

**Important:** This command does two things:
1. Creates an app named `my-agent-chatbot` (you can change this name)
2. **Configures a resource** named `"serving-endpoint"` that points to your actual serving endpoint with `CAN_QUERY` permission

The `app.yaml` file references this resource by name using `valueFrom: "serving-endpoint"`. The resource name must match between the app creation command and the `app.yaml` file.

**Step 2: Upload and Deploy**

From the project directory, run:

```bash
# Get your Databricks username
DATABRICKS_USERNAME=$(databricks current-user me | jq -r .userName)

# Sync the source code to Databricks
databricks sync . "/Users/$DATABRICKS_USERNAME/e2e-chatbot-app"

# Deploy the app
databricks apps deploy my-agent-chatbot --source-code-path "/Workspace/Users/$DATABRICKS_USERNAME/e2e-chatbot-app"
```

> **Note**: The deployment may take a few minutes to complete.

**Step 3: Get the App URL**

```bash
databricks apps get my-agent-chatbot | jq -r '.url'
```

This returns the URL where your app is hosted. You can now access and test your chatbot.

---

**For both deployment methods**, the app will have a dedicated service principal with:
- Automatic authentication via `CLIENT_ID` and `CLIENT_SECRET` environment variables (injected automatically)
- Access to the serving endpoint with `CAN_QUERY` permission
- Isolated credentials for security (never hardcode Personal Access Tokens)

**Important Security Notes:**
- Resources allow your app to securely connect to services without hardcoding sensitive values
- Each app gets its own service principal for isolation
- The app runs with least privilege - it only has the permissions you explicitly grant
- Never hardcode credentials in your code - use the automatic environment variables

See [Configure authorization in a Databricks app](https://docs.databricks.com/en/dev-tools/databricks-apps/authorization.html) for more details on app security.

### 3. Share the App

By default, only you can access the deployed app. To share it with others:

1. Go to your Databricks workspace
2. Navigate to **Apps** in the left sidebar
3. Find your app (`my-agent-chatbot`)
4. Click on the app and go to **Permissions**
5. Add users or groups and grant them appropriate permissions

See the [official documentation on app permissions](https://docs.databricks.com/en/dev-tools/databricks-apps/permissions.html) for more details.

## User Authorization

This app uses **user authorization** (also known as on-behalf-of-user authorization), which means it acts with the identity of each user who interacts with it. This provides several important benefits:

### Benefits of User Authorization

1. **Fine-Grained Access Control**: Each user's Unity Catalog permissions are automatically enforced, including:
   - Table and column-level permissions
   - Row-level filters
   - Column masks for sensitive data

2. **Compliance & Auditing**: All actions are performed with the user's identity, creating clear audit trails

3. **No Permission Escalation**: Users can only access data they already have permission to see

4. **Consistent Governance**: Access control policies are managed centrally in Unity Catalog, not in app code

### How It Works

According to the [Databricks Apps authorization documentation](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth#user-authorization&gsc.tab=0):

1. **Token Forwarding**: When a user accesses the app, Databricks forwards their access token in the `x-forwarded-access-token` HTTP header
2. **Token Retrieval**: The app retrieves this token using `st.context.headers.get('x-forwarded-access-token')`
3. **Authenticated Requests**: All SDK calls use this token instead of the app's service principal credentials
4. **Permission Enforcement**: Databricks enforces the user's Unity Catalog permissions on every query

### Authorization Scopes

The app declares which permissions it needs through authorization scopes in `app.yaml`:

```yaml
user_authorization:
  scopes:
    - "sql"  # Access SQL warehouses for querying data
    - "genai.genie"  # Access Genie spaces for AI assistance
```

**Important**: Users must consent to these scopes when they first access the app. Workspace admins can also grant consent on behalf of all users.

### Scope Configuration

You can customize the scopes based on your app's needs:

- **`sql`**: Required for querying SQL warehouses and Unity Catalog tables
- **`genai.genie`**: Required for Genie space access (if your agent uses Genie)
- **`iam.access-control:read`**: Default scope for reading user identity
- **`iam.current-user:read`**: Default scope for reading current user info

See the [full list of scopes](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth#user-authorization&gsc.tab=0) in the Databricks documentation.

### Local Development

For local development, you can set the `DATABRICKS_HOST` environment variable:

```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
```

Note that user authorization requires the app to be deployed to Databricks. For local testing, you can use app authorization by not passing the user token.

## Configuration

### Environment Variables

- **`SERVING_ENDPOINT`** (required): Name of the Databricks Model Serving endpoint to query
  - For local development: Set via `export SERVING_ENDPOINT=your-endpoint-name`
  - For Databricks Apps: The `app.yaml` references a resource named "serving-endpoint" using `valueFrom`. This resource must be configured when creating the app via `databricks apps create` (see deployment instructions below)

### Customization Options

#### Changing the App Title and Description

Edit `app.py` lines 95-97:

```python
st.title("🧱 Chatbot App")
st.write(f"A basic chatbot using your own serving endpoint.")
st.write(f"Endpoint name: `{SERVING_ENDPOINT}`")
```

#### Modifying Tool Call Display

Edit the `render_message()` function in `ui_components.py` to customize how tool calls are displayed.

#### Adjusting Feedback Options

The feedback mechanism uses Streamlit's `st.feedback()` with thumbs up/down. To change the feedback style, modify the `render_assistant_message_feedback()` function in `ui_components.py`.

### Understanding Feedback Functionality

The app automatically detects whether your endpoint supports feedback when it starts up. Here's how it works:

**Automatic Detection:**
```python
# From app.py line 24
ENDPOINT_SUPPORTS_FEEDBACK = endpoint_supports_feedback(SERVING_ENDPOINT)
```

This checks if your endpoint has a "feedback" served entity in its configuration. If detected:
- The app requests traces from the endpoint (to get `request_id`)
- Feedback buttons (👍/👎) appear below assistant responses
- User ratings are sent to the endpoint's feedback invocation API

**What happens if feedback is NOT supported:**
- The app works normally without any errors
- Feedback buttons simply don't appear
- No performance impact

**Implementation Details:**
- **Detection logic**: Located in `model_serving_utils.py` → `endpoint_supports_feedback()`
- **Feedback UI**: Located in `ui_components.py` → `render_assistant_message_feedback()`
- **Submission**: Located in `model_serving_utils.py` → `submit_feedback()`

**Feedback payload includes:**
- `request_id`: Links feedback to the specific response
- `rating`: "positive" (👍) or "negative" (👎)
- `source`: Identifies feedback came from this chatbot app

**To enable feedback on your endpoint:**

When deploying an agent using `agents.deploy()`, the feedback entity is typically configured automatically if you're using MLflow 2.21.2+ and have set up your agent with the Agent Framework. For more details on agent deployment with feedback, see the [Databricks Agent Framework documentation](https://docs.databricks.com/en/generative-ai/agent-framework/create-agent.html).

If feedback isn't working, verify the endpoint configuration as described in the Troubleshooting section below.

## Supported Endpoint Types

### 1. Chat Completions (`chat/completions`)

Standard foundation model endpoints that return chat completions in OpenAI-compatible format.

**Response Format:**
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "Response text"
    }
  }]
}
```

### 2. ChatAgent (`agent/v2/chat`)

Agents that follow the ChatAgent protocol with support for tool calls and structured responses.

**Streaming Format:** Uses `ChatAgentChunk` from MLflow types

**Features:**
- Message accumulation across chunks
- Tool call streaming and accumulation
- Multiple message support

### 3. ResponsesAgent (`agent/v1/responses`)

Agents using the ResponsesAgent protocol with streaming events.

**Streaming Format:** Uses `ResponsesAgentStreamEvent` from MLflow types

**Event Types:**
- `message`: Text responses from the agent
- `function_call`: Tool invocations
- `function_call_output`: Tool execution results

## Troubleshooting

### Common Issues

#### "Unable to determine serving endpoint"

**Error Message:**
```
AssertionError: Unable to determine serving endpoint to use for chatbot app...
```

**Solution:**
- **For local development**: Ensure `SERVING_ENDPOINT` environment variable is set:
  ```bash
  export SERVING_ENDPOINT=your-endpoint-name
  ```

- **For Databricks Apps**: The serving endpoint is NOT configured in `app.yaml` directly. You must configure it as a resource when creating the app:
  
  **Via UI:**
  1. In the Apps UI, go to **App resources** section
  2. Click **+ Add resource**
  3. Select your serving endpoint and set permission to `CAN_QUERY`
  4. Set the resource key to `"serving-endpoint"` (must match the `valueFrom` value in `app.yaml`)
  
  **Via CLI:**
  1. Use `databricks apps create` with a resource configuration
  2. Ensure the resource name matches the `valueFrom` value in `app.yaml` (default is `"serving-endpoint"`)
  3. Grant `CAN_QUERY` permission to the resource
  
  See the deployment instructions above for complete steps for both methods.

#### Streaming Errors

If streaming fails, the app automatically falls back to non-streaming mode. Check the logs for specific error messages.

**Common causes:**
- Network timeouts
- Endpoint not responding to streaming requests
- Invalid message format

#### Feedback Not Working

The feedback feature (thumbs up/down buttons) only appears when **both** of the following conditions are met:

1. **The endpoint has a feedback entity configured**: The endpoint must have a served entity named "feedback" in its configuration
2. **The endpoint returns request traces**: The endpoint must return `databricks_request_id` in the response

**How to check if your endpoint supports feedback:**

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
endpoint = w.serving_endpoints.get("your-endpoint-name")

# Check if feedback entity exists
served_entities = [entity.name for entity in endpoint.config.served_entities]
print(f"Served entities: {served_entities}")
print(f"Has feedback: {'feedback' in served_entities}")
```

**Why feedback might not be working:**

- **Most common**: Your endpoint was not deployed with the feedback capability. This is a specific Databricks feature that must be configured during agent deployment.
- **Foundation model endpoints**: Standard foundation model endpoints typically do NOT have feedback entities configured
- **Custom agents**: Only agents deployed with `agents.deploy()` that explicitly include feedback configuration will support this feature
- **Permissions**: Ensure you have proper permissions to submit feedback to the endpoint

**Supported endpoint types for feedback:**
- ✅ Agents deployed with `agents.deploy()` (if feedback is configured)
- ✅ Agent Bricks with feedback enabled
- ❌ Most foundation model endpoints
- ❌ Agents without feedback entity in served_entities

If your endpoint doesn't support feedback, the app will still work normally - you just won't see the thumbs up/down buttons after responses.

#### Import Errors

**Error Message:**
```
ModuleNotFoundError: No module named 'mlflow'
```

**Solution:**
```bash
pip install -r requirements.txt
```

### Debug Mode

To enable detailed logging, modify the logging level in `model_serving_utils.py`:

```python
logging.basicConfig(
    format="%(levelname)s [%(asctime)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.DEBUG  # Change to DEBUG for verbose logging
)
```

## Development Notes

### Message State Management

The app uses a class-based approach for messages (`messages.py`) to avoid `isinstance` comparison issues across Streamlit reruns. Keep message classes in a separate module to maintain stability.

### Streaming Implementation

The app implements sophisticated streaming handlers that:
1. Accumulate partial responses as chunks arrive
2. Handle out-of-order message chunks (using `OrderedDict`)
3. Properly merge tool call arguments that arrive in multiple chunks
4. Update the UI incrementally for a smooth user experience

### Task Type Detection

The app automatically detects the endpoint's task type on the first message using the Databricks SDK. This ensures compatibility with different endpoint types without manual configuration.

## Resources

### Databricks Documentation
- [Databricks Agent Framework - Chat App](https://docs.databricks.com/en/generative-ai/agent-framework/chat-app.html) - Original guide this app is based on
- [Databricks Apps Documentation](https://docs.databricks.com/en/dev-tools/databricks-apps/index.html) - Complete apps platform documentation
- [Add Resources to Apps](https://docs.databricks.com/en/dev-tools/databricks-apps/resources.html) - How to configure serving endpoints and other resources
- [Configure App Authorization](https://docs.databricks.com/en/dev-tools/databricks-apps/authorization.html) - Service principal and permissions
- [App Permissions](https://docs.databricks.com/en/dev-tools/databricks-apps/permissions.html) - Sharing apps with users

### Other Documentation
- [MLflow Deployments Client](https://mlflow.org/docs/latest/python_api/mlflow.deployments.html) - API for querying endpoints
- [Streamlit Documentation](https://docs.streamlit.io/) - Streamlit framework reference

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Contributing

This application is based on Databricks' official templates. For improvements or bug fixes, consider:
1. Testing changes locally first
2. Verifying compatibility with all three endpoint types
3. Ensuring streaming and non-streaming modes both work
4. Testing feedback functionality if modified

## Support

For issues related to:
- **Databricks Platform**: Contact Databricks Support or consult the Knowledge Base
- **This Application**: Review the troubleshooting section or check application logs
- **Agent Development**: See [Author AI Agents in Code](https://docs.databricks.com/en/generative-ai/agent-framework/create-agent.html)

