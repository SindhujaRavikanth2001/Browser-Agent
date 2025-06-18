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

import re, requests

def remove_chinese_and_punct(text):
    """
    Returns the part of the text before the first Chinese character.
    If no Chinese character is found, returns the whole text.
    """
    match = re.search(r'[\u4e00-\u9fff]', text)
    if match:
        return text[:match.start()]
    return text

def annotate_invalid_links(text: str) -> str:
    """
    Finds all markdown links [label](url) in `text`, does a HEAD request
    to each `url`, and if it’s 4xx/5xx (or errors), appends ⚠️ to the link.
    """
    def check(url):
        try:
            r = requests.head(url, allow_redirects=True, timeout=5)
            return r.status_code < 400
        except:
            return False

    def repl(m):
        label, url = m.group(1), m.group(2)
        ok = check(url)
        return f"[{label}]({url})" + ("" if ok else " ⚠️(broken)")

    return re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', repl, text)


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


def save_comprehensive_response(query: str, agent_response: str, agent_messages: List = None, is_partial: bool = False, is_error: bool = False):
    """Save only the final response to file."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"responses/agent_response_{timestamp}.txt"
        
        # Ensure responses directory exists
        os.makedirs("responses", exist_ok=True)
        
        with open(filename, "w", encoding="utf-8") as f:
            # Write header
            f.write("="*80 + "\n")
            f.write(f"QUERY: {query}\n")
            f.write("="*80 + "\n\n")
            
            # Write status if partial or error
            if is_partial:
                f.write("⚠️ PARTIAL RESPONSE (Timed out)\n\n")
            elif is_error:
                f.write("❌ ERROR RESPONSE\n\n")
            
            # Write only the final response
            f.write("RESPONSE:\n")
            f.write(str(agent_response))
            f.write("\n\n")
        
        print(f"Response saved to {filename}")
        
    except Exception as e:
        print(f"Error saving response: {e}")


class UserMessage(BaseModel):
    content: str


async def process_message_with_direct_scraping(agent, message: str, max_timeout: int = 400):
    """Process message with direct scraping and chunked LLM processing."""
    screenshot_base64 = None
    try:
        # Enhanced URL detection
        urls = []
        full_url_pattern = r'https?://[^\s]+'
        full_urls = re.findall(full_url_pattern, message)
        urls.extend(full_urls)
        
        if not urls:
            words = message.split()
            for word in words:
                word = word.rstrip('.,!?;')
                if ('.' in word and 
                    not word.startswith('.') and 
                    not word.endswith('.') and
                    len(word.split('.')[-1]) >= 2 and
                    not word.startswith('http') and
                    ' ' not in word):
                    urls.append(word)
        
        print(f"🔍 Found URLs: {urls}")
        
        if urls:
            url = urls[0]
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            print(f"🔗 URL detected and normalized: {url}")
            scraped_content = scrape_page_content(url)
            
            if scraped_content and not scraped_content.startswith("Error"):
                chunks = chunk_content(scraped_content, chunk_size=4000)
                print(f"📦 Content split into {len(chunks)} chunks")
                enhanced_message = f"""
Please respond in English only. Use 'Source:' instead of '来源:', if the user asks for sources/references. Format URLs as markdown links.
{message}

I have scraped the complete content from the webpage. Here is the full content:

COMPLETE SCRAPED CONTENT:
{scraped_content[:8000]}

Based on this content, address the user's prompt in English only. Strictly do not include any other language.
"""
                raw = await asyncio.wait_for(
                    agent.llm.ask(enhanced_message,
                    temperature=0.7),
                    timeout=max_timeout
                )
                response = annotate_invalid_links(str(raw))
                response = remove_chinese_and_punct(response)
            else:
                print(f"❌ Scraping failed: {scraped_content}")
                raw = await asyncio.wait_for(
                    agent.llm.ask(message,
                    temperature=0.7),
                    timeout=max_timeout
                )
                response = annotate_invalid_links(str(raw))
                response = remove_chinese_and_punct(response)
        else:
            print("ℹ️ No URL detected in message, processing with direct response")
            # Use direct response generation
            response_data = await process_message_with_direct_scraping(
                self.agent,
                user_message,
                max_timeout=60
            )
        
        # Save response
        if response:
            agent_messages = getattr(agent, 'memory', None)
            if agent_messages and hasattr(agent_messages, 'messages'):
                agent_messages = agent_messages.messages
            else:
                agent_messages = []
            save_comprehensive_response(message, str(response), agent_messages)
        
        return {
            "response": str(response) if response else "No response generated",
            "base64_image": screenshot_base64
        }
        
    except AsyncTimeoutError:
        print(f"Agent execution timed out after {max_timeout} seconds")
        
        # Extract the best available response from memory
        best_response = "Request timed out while processing."
        
        if hasattr(agent, 'memory') and hasattr(agent.memory, 'messages'):
            assistant_responses = []
            for msg in agent.memory.messages:
                if hasattr(msg, 'role') and msg.role == 'assistant' and hasattr(msg, 'content'):
                    content = str(msg.content)
                    if len(content) > 100:  # Only consider substantial responses
                        assistant_responses.append(content)
            
            if assistant_responses:
                # Get the longest response or combine multiple if needed
                longest_response = max(assistant_responses, key=len)
                
                if len(longest_response) > 300:
                    best_response = f"Partial response (timed out):\n\n{longest_response}"
                elif len(assistant_responses) > 1:
                    # Combine multiple responses
                    combined = "\n\n---\n\n".join(assistant_responses[-2:])
                    best_response = f"Partial response (timed out):\n\n{combined}"
                else:
                    best_response = f"Partial response (timed out):\n\n{longest_response}"
        
        save_comprehensive_response(message, best_response, is_partial=True)
        return {
            "response": best_response,
            "base64_image": screenshot_base64
        }
    
    except Exception as e:
        error_msg = f"Error during agent execution: {e}"
        print(error_msg)
        save_comprehensive_response(message, error_msg, is_error=True)
        return {
            "response": error_msg,
            "base64_image": screenshot_base64
        }


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
                config = config_instance._config
                
                llm_instance = LLM(
                    model_name="Qwen/Qwen-7B-Chat",  # switched to chat model
                    api_type="huggingface",
                    use_auth_token=True
                )

                bash_tool = Bash(config=config)
                browser_use_tool = BrowserUseTool(llm=llm_instance)
                create_chat_completion_tool = CreateChatCompletion()
                planning_tool = PlanningTool()
                str_replace_editor_tool = StrReplaceEditor()
                terminate_tool = Terminate()

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

        self.setup_routes()

        if os.path.exists(self.frontend_dir):
            self.app.mount("/", StaticFiles(directory=self.frontend_dir, html=True), name="static")

    def setup_routes(self):
        """Set up API routes."""

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.active_websockets.append(websocket)

            try:
                await websocket.send_json({"type": "connect", "status": "success"})
                logger.info("Client connected via WebSocket")

                while True:
                    data = await websocket.receive_json()
                    logger.info(f"Received WebSocket message: {data}")

                    if "content" in data:
                        user_message = data["content"]
                        logger.info(f"Processing message: {user_message}")
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
            return JSONResponse({
                "status": "online",
                "agent_initialized": self.agent is not None
            })

        @self.app.post("/api/message")
        async def handle_message(request: UserMessage):
            try:
                if not self.agent:
                    return JSONResponse(
                        status_code=500,
                        content={"response": "Agent not initialized", "status": "error"}
                    )

                response_data = await process_message_with_direct_scraping(
                    self.agent,
                    request.content,
                    max_timeout=60
                )
                
                if isinstance(response_data, dict):
                    response_content = response_data.get("response", "")
                    screenshot = response_data.get("base64_image", None)
                else:
                    response_content = str(response_data)
                    screenshot = None
                
                result = {
                    "response": response_content,
                    "status": "success"
                }
                
                if screenshot:
                    result["base64_image"] = screenshot
                
                return JSONResponse(result)
                
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

            await self.broadcast_message("agent_action", {
                "action": "Processing",
                "details": f"Generating response for: {user_message}"
            })

            # Use direct response generation - NO AGENT.RUN
            try:
                # Check if this is a simple question
                is_simple_request = True  # Treat all requests as simple for direct response
                
                if is_simple_request and 'http' not in user_message:
                    prefix = (
                        "Please respond in English only. "
                        "Use 'Source:' instead of '来源:', if the user asks for sources/references."
                        "Format URLs as markdown links (e.g. [text](url)).\n\n"
                    )
                    raw = await self.agent.llm.ask(prefix + user_message, temperature=0.7)
                    response = annotate_invalid_links(str(raw))
                    response = remove_chinese_and_punct(response)

                    await self.broadcast_message("agent_message", {
                        "content": str(response)
                    })
                    return
                else:
                    # For complex requests, use the processing function
                    response_data = await asyncio.wait_for(
                        process_message_with_direct_scraping(
                            self.agent,
                            user_message,
                            max_timeout=60
                        ),
                        timeout=90
                    )

                    if isinstance(response_data, dict):
                        response_content = response_data.get("response", "")
                        screenshot = response_data.get("base64_image", None)
                    else:
                        response_content = str(response_data)
                        screenshot = None

                    await self.broadcast_message("agent_message", {
                        "content": response_content
                    })

                    if screenshot:
                        await self.broadcast_message("browser_state", {
                            "base64_image": screenshot
                        })

            except asyncio.TimeoutError:
                await self.broadcast_message("agent_message", {
                    "content": "I apologize, but the request timed out. Please try a simpler question."
                })

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            await self.broadcast_message("error", {
                "message": f"Error processing message: {str(e)}"
            })

    async def broadcast_message(self, message_type: str, data: dict):
        """Broadcast a message to all connected WebSocket clients."""
        message = {"type": message_type, **data}

        for websocket in self.active_websockets:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to client: {str(e)}")
                if websocket in self.active_websockets:
                    self.active_websockets.remove(websocket)

    def patch_agent_methods(self):
        """Patch the agent methods to capture responses immediately."""
        if not self.agent:
            return

        ui = self
        agent = self.agent

        if hasattr(agent, "execute_tool"):
            original_execute = agent.execute_tool

            async def patched_execute_tool(command, *args, **kwargs):
                tool_name = command.function.name
                arguments = command.function.arguments

                # 1) Announce which tool is running
                await ui.broadcast_message("agent_action", {
                    "action": f"Tool: {tool_name}",
                    "details": f"Arguments: {arguments}"
                })

                # 2) Run the original tool
                result = await original_execute(command, *args, **kwargs)

                # 3) If it's the terminate tool, gather and broadcast the best response
                if tool_name == "terminate":
                    msgs = getattr(agent.memory, "messages", [])
                    replies = [
                        str(m.content)
                        for m in msgs
                        if getattr(m, "role", None) == "assistant"
                           and hasattr(m, "content")
                           and len(str(m.content)) > 50
                    ]
                    best = ""
                    if replies:
                        best = max(replies, key=len)
                        if len(best) < 800 and len(replies) > 1:
                            combo = "\n\n".join(replies[-3:])
                            if len(combo) > len(best):
                                best = combo

                    await ui.broadcast_message("agent_message", {
                        "content": best or
                                   "I've finished processing. Please check above or rephrase your request."
                    })

                # 4) For browser_use extraction, broadcast a content preview
                if tool_name == "browser_use" and hasattr(result, "output"):
                    out = str(result.output)
                    if len(out) > 200:
                        preview = out[:2000] + ("…" if len(out) > 2000 else "")
                        await ui.broadcast_message("agent_message", {
                            "content": f"Extracted content:\n\n{preview}"
                        })

                return result

            agent.execute_tool = patched_execute_tool

    def run(self, host: str = "0.0.0.0", port: int = 8000):
        """Run the UI server."""
        logger.info(f"Starting OpenManus UI server at http://{host}:{port}")
        uvicorn.run(self.app, host=host, port=port)


if __name__ == "__main__":
    ui_server = OpenManusUI()
    ui_server.run()
