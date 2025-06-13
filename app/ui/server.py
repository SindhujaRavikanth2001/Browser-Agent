import asyncio
import os
from datetime import datetime
from asyncio import TimeoutError as AsyncTimeoutError
import json
from typing import Dict, List, Optional
from contextvars import ContextVar
import requests
from bs4 import BeautifulSoup
import re

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


def scrape_page_content(url: str) -> str:
    """
    Scrape complete page content using BeautifulSoup.
    Returns clean text content of the entire page.
    """
    try:
        print(f"🔍 Scraping page content from: {url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "header", "footer"]):
            script.decompose()
        
        # Get text content
        text = soup.get_text()
        
        # Clean up text
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        print(f"✅ Successfully scraped {len(text)} characters from page")
        print(f"📄 COMPLETE PAGE CONTENT:\n{'-'*80}\n{text}\n{'-'*80}")
        
        return text
        
    except Exception as e:
        print(f"❌ Error scraping page: {e}")
        return f"Error scraping page: {e}"


def chunk_content(content: str, chunk_size: int = 4000) -> List[str]:
    """
    Split content into chunks for processing.
    """
    chunks = []
    words = content.split()
    
    current_chunk = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + 1 > chunk_size and current_chunk:
            chunks.append(' '.join(current_chunk))
            current_chunk = [word]
            current_length = len(word)
        else:
            current_chunk.append(word)
            current_length += len(word) + 1
    
    if current_chunk:
        chunks.append(' '.join(current_chunk))
    
    return chunks


# Enhanced response saving with better formatting
def save_comprehensive_response(query: str, agent_response: str, agent_messages: List = None, is_partial: bool = False, is_error: bool = False):
    """Save comprehensive agent response with full conversation history and extracted content."""
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
            
            # Write the main response
            f.write("AGENT RESPONSE:\n")
            f.write(agent_response)
            f.write("\n\n")
            
            # If we have agent messages, extract and format them nicely
            if agent_messages:
                f.write("="*80 + "\n")
                f.write("DETAILED CONVERSATION HISTORY:\n")
                f.write("="*80 + "\n\n")
                
                extracted_content_sections = []
                user_goal_responses = []
                
                for i, msg in enumerate(agent_messages):
                    if hasattr(msg, 'role') and hasattr(msg, 'content') and msg.content:
                        f.write(f"{msg.role.upper()}: {msg.content}\n\n")
                        
                        # Look for extracted content
                        if "extracted from page" in msg.content.lower() or "extraction" in msg.content.lower():
                            extracted_content_sections.append(msg.content)
                        
                        # Look for responses to user goals (survey questions, etc.)
                        if any(keyword in msg.content.lower() for keyword in [
                            "survey questions", "questions:", "questionnaire", "1.", "2.", "3."
                        ]) and len(msg.content) > 200:
                            user_goal_responses.append(msg.content)
                
                # Add special sections for extracted content and goal responses
                if extracted_content_sections:
                    f.write("="*80 + "\n")
                    f.write("EXTRACTED CONTENT SECTIONS:\n")
                    f.write("="*80 + "\n\n")
                    for section in extracted_content_sections:
                        f.write(section)
                        f.write("\n" + "-"*40 + "\n")
                
                if user_goal_responses:
                    f.write("="*80 + "\n")
                    f.write("RESPONSES TO USER GOALS:\n")
                    f.write("="*80 + "\n\n")
                    for response in user_goal_responses:
                        f.write(response)
                        f.write("\n" + "-"*40 + "\n")
        
        print(f"Comprehensive response saved to {filename}")
        
    except Exception as e:
        print(f"Error saving comprehensive response: {e}")


class UserMessage(BaseModel):
    content: str


# Enhanced timeout handling with direct scraping and chunked processing
async def process_message_with_direct_scraping(agent, message: str, max_timeout: int = 720):
    """Process message with direct scraping and chunked LLM processing."""
    try:
        # Check if message contains a URL
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, message)
        
        if urls:
            url = urls[0]  # Use first URL found
            print(f"🔗 URL detected: {url}")
            
            # Scrape complete content directly
            scraped_content = scrape_page_content(url)
            
            if scraped_content and not scraped_content.startswith("Error"):
                # Chunk the content
                chunks = chunk_content(scraped_content, chunk_size=4000)
                print(f"📦 Content split into {len(chunks)} chunks")
                
                # Process with LLM using chunked content
                enhanced_message = f"""
{message}

I have scraped the complete content from the webpage. Here is the full content divided into chunks:

COMPLETE SCRAPED CONTENT ({len(chunks)} chunks):

"""
                for i, chunk in enumerate(chunks, 1):
                    enhanced_message += f"\n--- CHUNK {i}/{len(chunks)} ---\n{chunk}\n"
                
                enhanced_message += f"""

Please process this complete content to address the user's request. All the content from the webpage is provided above - no need to browse or scroll.
"""
                
                response = await asyncio.wait_for(
                    agent.run(enhanced_message, max_steps=12),
                    timeout=max_timeout
                )
            else:
                # Fall back to original message if scraping failed
                response = await asyncio.wait_for(
                    agent.run(message, max_steps=12),
                    timeout=max_timeout
                )
        else:
            # No URL detected, process normally
            response = await asyncio.wait_for(
                agent.run(message, max_steps=12),
                timeout=max_timeout
            )
        
        # Save comprehensive response
        if response:
            agent_messages = getattr(agent, 'messages', []) or []
            save_comprehensive_response(message, response, agent_messages)
            
        return response
        
    except AsyncTimeoutError:
        print(f"Agent execution timed out after {max_timeout} seconds")
        if hasattr(agent, 'memory') and agent.memory.messages:
            partial_sections = []
            
            for msg in agent.memory.messages:
                if hasattr(msg, 'content') and msg.content:
                    content = str(msg.content)
                    
                    if "extracted from page" in content.lower():
                        partial_sections.append(f"EXTRACTED CONTENT:\n{content}\n")
                    elif any(keyword in content.lower() for keyword in [
                        "survey questions", "questions:", "questionnaire"
                    ]) and len(content) > 100:
                        partial_sections.append(f"GOAL RESPONSE:\n{content}\n")
                    elif "tool" in content.lower() and len(content) > 50:
                        partial_sections.append(f"TOOL RESULT:\n{content[:500]}...\n")
            
            partial_response = "PARTIAL RESPONSE (Timed out):\n\n"
            partial_response += "\n".join(partial_sections[-10:])
            
            save_comprehensive_response(message, partial_response, agent.memory.messages, is_partial=True)
            return partial_response
        else:
            error_msg = "Agent timed out and no partial response available"
            save_comprehensive_response(message, error_msg, is_error=True)
            return error_msg
    
    except Exception as e:
        error_msg = f"Error during agent execution: {e}"
        print(error_msg)
        agent_messages = getattr(agent, 'messages', []) if hasattr(agent, 'messages') else []
        save_comprehensive_response(message, error_msg, agent_messages, is_error=True)
        return error_msg


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
                    model_name="Qwen/Qwen2.5-72B-Instruct",
                    api_type="huggingface"
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
            """Handle POST message requests with enhanced response formatting."""
            try:
                if not self.agent:
                    return JSONResponse(
                        status_code=500,
                        content={"response": "Agent not initialized", "status": "error"}
                    )

                # Use direct scraping approach
                response = await process_message_with_direct_scraping(
                    self.agent,
                    request.content,
                    max_timeout=720  # 12 minutes
                )
                
                return JSONResponse({
                    "response": response, 
                    "status": "success",
                    "message": "Response has been saved to the responses/ directory with full conversation history."
                })
                
            except Exception as e:
                logger.error(f"Error in handle_message: {str(e)}", exc_info=True)
                error_response = f"Server error: {str(e)}"
                save_comprehensive_response(request.content, error_response, is_error=True)
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

            # Use direct scraping approach
            response = await process_message_with_direct_scraping(
                self.agent,
                user_message,
                max_timeout=720  # 12 minutes
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