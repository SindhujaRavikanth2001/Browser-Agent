import asyncio
import os
from datetime import datetime
from asyncio import TimeoutError as AsyncTimeoutError
import json
from typing import Dict, List, Optional
from contextvars import ContextVar

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent.manus import Manus
from app.llm import LLM
from app.logger import logger
from app.schema import ToolCall, Message, Memory
from app.config import Config
from app.tool import ToolCollection
from app.tool.bash import Bash
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.create_chat_completion import CreateChatCompletion
from app.tool.planning import PlanningTool
from app.tool.str_replace_editor import StrReplaceEditor
from app.tool.terminate import Terminate
from app.exceptions import TokenLimitExceeded


# Define a global context variable for the Manus agent
g = ContextVar('g', default=None)


class UserMessage(BaseModel):
    content: str


# Global helper functions (moved outside the class)
async def process_message_with_better_timeout(agent, message: str, max_timeout: int = 300):
    """Process message with better timeout handling and response saving"""
    try:
        # Increase timeout to 5 minutes for HuggingFace models
        response = await asyncio.wait_for(
            agent.run(message, max_steps=8),  # Reduced max_steps for faster completion
            timeout=max_timeout
        )
        
        # Ensure response is saved
        if response:
            save_response_to_file(message, response)
            
        return response
        
    except AsyncTimeoutError:
        print(f"Agent execution timed out after {max_timeout} seconds")
        # Try to get partial results
        if hasattr(agent, 'memory') and agent.memory.messages:
            partial_response = "PARTIAL RESPONSE (Timed out):\n"
            for msg in agent.memory.messages[-5:]:  # Last 5 messages
                if hasattr(msg, 'content') and msg.content:
                    partial_response += f"{msg.role}: {str(msg.content)[:200]}...\n"
            
            # Save partial response
            save_response_to_file(message, partial_response, is_partial=True)
            return partial_response
        else:
            error_msg = "Agent timed out and no partial response available"
            save_response_to_file(message, error_msg, is_error=True)
            return error_msg
    
    except Exception as e:
        error_msg = f"Error during agent execution: {e}"
        print(error_msg)
        save_response_to_file(message, error_msg, is_error=True)
        return error_msg


def save_response_to_file(query: str, response: str, is_partial: bool = False, is_error: bool = False):
    """Save agent response to file"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Determine filename based on response type
        if is_error:
            filename = f"responses/agent_error_{timestamp}.txt"
        elif is_partial:
            filename = f"responses/agent_partial_{timestamp}.txt"
        else:
            filename = f"responses/agent_response_{timestamp}.txt"
        
        # Create directory if it doesn't exist
        os.makedirs("responses", exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"Query: {query}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Status: {'ERROR' if is_error else 'PARTIAL' if is_partial else 'COMPLETE'}\n")
            f.write("="*80 + "\n\n")
            f.write(response)
        
        print(f"Response saved to {filename}")
        
    except Exception as e:
        print(f"Error saving response: {e}")


class OpenManusUI:
    """UI server for OpenManus."""

    def __init__(self, static_dir: Optional[str] = None):
        self.app = FastAPI(title="OpenManus UI")
        self.agent: Optional[Manus] = None
        self.active_websockets: List[WebSocket] = []
        self.frontend_dir = static_dir or os.path.join(os.path.dirname(__file__), "../../frontend/openmanus-ui/dist")

        # Configure CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Initialize Manus agent on startup
        @self.app.on_event("startup")
        async def startup_event():
            logger.info("Application startup: Initializing Manus agent...")
            try:
                config_instance = Config()
                config = config_instance._config # Access the internal _config attribute which holds the AppConfig
                
                # Explicitly create the LLM instance here and pass it to Manus and other tools
                llm_instance = LLM(
                    model_name="Qwen/Qwen2.5-72B-Instruct", # Or use config.llm.get("huggingface_llm_config_name").model if applicable
                    api_type="huggingface" # Ensure this matches your config for HuggingFaceClient
                )

                # Instantiate individual tools with the config
                bash_tool = Bash(config=config)
                browser_use_tool = BrowserUseTool(llm=llm_instance) # Pass the existing LLM instance
                create_chat_completion_tool = CreateChatCompletion()
                planning_tool = PlanningTool()
                str_replace_editor_tool = StrReplaceEditor()
                terminate_tool = Terminate()

                # Create a ToolCollection instance with the instantiated tools
                manus_tools = ToolCollection(
                    bash_tool,
                    browser_use_tool,
                    create_chat_completion_tool,
                    planning_tool,
                    str_replace_editor_tool,
                    terminate_tool
                )
                
                self.agent = Manus(config=config, tools=manus_tools, llm=llm_instance)
                self.patch_agent_methods()
                logger.info("Manus agent initialized successfully on startup.")
            except Exception as e:
                logger.error(f"Error initializing Manus agent on startup: {str(e)}")
                # Re-raise the exception to prevent the server from starting with a broken agent
                raise

        # Set up routes
        self.setup_routes()

        # Mount static files if directory exists
        if os.path.exists(self.frontend_dir):
            self.app.mount("/", StaticFiles(directory=self.frontend_dir, html=True), name="static")

    def setup_routes(self):
        """Set up API routes."""

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.active_websockets.append(websocket)

            try:
                # Send initial connection success
                await websocket.send_json({"type": "connect", "status": "success"})
                logger.info("Client connected via WebSocket")

                # Handle messages
                while True:
                    data = await websocket.receive_json()
                    logger.info(f"Received WebSocket message: {data}")

                    if "content" in data:
                        user_message = data["content"]
                        logger.info(f"Processing message: {user_message}")

                        # Process the message
                        asyncio.create_task(self.process_message(user_message))

            except WebSocketDisconnect:
                if websocket in self.active_websockets:
                    self.active_websockets.remove(websocket)
                logger.info("Client disconnected from WebSocket")

            except Exception as e:
                logger.error(f"WebSocket error: {str(e)}", exc_info=True)
                if websocket in self.active_websockets:
                    self.active_websockets.remove(websocket)

        @self.app.get("/api/status")
        async def get_status():
            """Check if the server is running."""
            return JSONResponse({
                "status": "online",
                "agent_initialized": self.agent is not None
            })

        @self.app.post("/api/message")
        async def handle_message(request: UserMessage):
            """Handle POST message requests."""
            try:
                if not self.agent:
                    return JSONResponse(
                        status_code=500,
                        content={"response": "Agent not initialized", "status": "error"}
                    )

                # Use the improved timeout handler with the class instance agent
                response = await process_message_with_better_timeout(
                    self.agent,  # Use self.agent instead of undefined 'agent'
                    request.content,  # Use request.content instead of request.message
                    max_timeout=300  # 5 minutes
                )
                
                return JSONResponse({
                    "response": response, 
                    "status": "success"
                })
                
            except Exception as e:
                logger.error(f"Error in handle_message: {str(e)}", exc_info=True)
                error_response = f"Server error: {str(e)}"
                save_response_to_file(request.content, error_response, is_error=True)
                return JSONResponse(
                    status_code=500,
                    content={"response": error_response, "status": "error"}
                )

        @self.app.get("/")
        async def get_index():
            """Serve the index.html file."""
            index_path = os.path.join(self.frontend_dir, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return {"message": "Frontend not built yet. Please run 'npm run build' in the frontend directory."}

    async def process_message(self, user_message: str):
        """Process a user message via WebSocket."""
        try:
            if not self.agent:
                await self.broadcast_message("error", {"message": "Agent not initialized"})
                return

            # Broadcast that we're starting to process
            await self.broadcast_message("agent_action", {
                "action": "Processing",
                "details": f"Starting to process: {user_message}"
            })

            # Use the improved timeout handler
            response = await process_message_with_better_timeout(
                self.agent,
                user_message,
                max_timeout=300
            )

            # Broadcast the final response
            await self.broadcast_message("agent_response", {
                "response": response
            })

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            await self.broadcast_message("error", {
                "message": f"Error processing message: {str(e)}"
            })

    async def broadcast_message(self, message_type: str, data: dict):
        """Broadcast a message to all connected WebSocket clients."""
        message = {"type": message_type, **data}

        # Add extra logging for browser state messages
        if message_type == "browser_state" and "base64_image" in data:
            image_data = data["base64_image"]
            logger.info(f"Broadcasting browser image: {len(image_data) if image_data else 0} bytes")

        for websocket in self.active_websockets:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to client: {str(e)}")
                # Remove broken connections
                if websocket in self.active_websockets:
                    self.active_websockets.remove(websocket)

    def patch_agent_methods(self):
        """Patch the agent methods to intercept and broadcast relevant information."""
        if not self.agent:
            return

        # Store reference to self for use in closures
        server_self = self

        # Patch browser state method
        if hasattr(self.agent, "get_browser_state"):
            original_get_browser_state = self.agent.get_browser_state

            async def patched_get_browser_state(*args, **kwargs):
                result = await original_get_browser_state(*args, **kwargs)

                # If browser has a screenshot, broadcast it
                if hasattr(self.agent, "_current_base64_image") and self.agent._current_base64_image:
                    # Explicitly capture and send the screenshot to the UI
                    await server_self.broadcast_message("browser_state", {
                        "base64_image": self.agent._current_base64_image
                    })
                    logger.info("Browser screenshot captured and broadcasted")

                return result

            self.agent.get_browser_state = patched_get_browser_state

        # Patch think method
        if hasattr(self.agent, "think"):
            original_think = self.agent.think

            async def patched_think(*args, **kwargs):
                # Log thinking step
                await server_self.broadcast_message("agent_action", {
                    "action": "Agent Thinking",
                    "details": "Analyzing current state and deciding next actions..."
                })

                result = await original_think(*args, **kwargs)
                return result

            self.agent.think = patched_think

        # Patch execute_tool method
        if hasattr(self.agent, "execute_tool"):
            original_execute_tool = self.agent.execute_tool

            async def patched_execute_tool(command, *args, **kwargs):
                tool_name = command.function.name
                arguments = command.function.arguments

                # Log the tool execution
                await server_self.broadcast_message("agent_action", {
                    "action": f"Tool: {tool_name}",
                    "details": f"Arguments: {arguments}"
                })

                # Special handling for browser_use tool
                is_browser_tool = tool_name in ["browser_use", "browser"]

                # Execute the tool
                result = await original_execute_tool(command, *args, **kwargs)

                # If it's a browser tool, wait for the screenshot
                if is_browser_tool and hasattr(self.agent, "_current_base64_image"):
                    await server_self.broadcast_message("browser_state", {
                        "base64_image": self.agent._current_base64_image
                    })

                return result

            self.agent.execute_tool = patched_execute_tool

        # Patch memory methods
        if hasattr(self.agent, "memory"):
            from app.schema import Memory
            original_add_message = Memory.add_message

            def patched_add_message(self, message, *args, **kwargs):
                # Call the original method
                original_add_message(self, message, *args, **kwargs)
                
                # If the message has an image, broadcast it
                if hasattr(message, "base64_image") and message.base64_image:
                    asyncio.create_task(server_self.broadcast_message("message", {
                        "role": message.role,
                        "content": message.content,
                        "base64_image": message.base64_image
                    }))
                else:
                    # Broadcast the message without image
                    asyncio.create_task(server_self.broadcast_message("message", {
                        "role": message.role,
                        "content": message.content
                    }))

            # Patch the method at the class level
            Memory.add_message = patched_add_message

    def run(self, host: str = "0.0.0.0", port: int = 8000):
        """Run the UI server."""
        logger.info(f"Starting OpenManus UI server at http://{host}:{port}")
        uvicorn.run(self.app, host=host, port=port)


# Entry point to run the server directly
if __name__ == "__main__":
    ui_server = OpenManusUI()
    ui_server.run()