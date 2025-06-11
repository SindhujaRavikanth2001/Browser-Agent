import asyncio
import base64
import json
from typing import Generic, Optional, TypeVar, Any
import logging

from browser_use import Browser as BrowserUseBrowser
from browser_use import BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.dom.service import DomService
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from app.config import config
from app.llm import LLM
from app.tool.base import BaseTool, ToolResult
from app.tool.web_search import WebSearch


_BROWSER_DESCRIPTION = """
Interact with a web browser to perform various actions such as navigation, element interaction, content extraction, and tab management. This tool provides a comprehensive set of browser automation capabilities:

Navigation:
- 'go_to_url': Go to a specific URL in the current tab
- 'go_back': Go back
- 'refresh': Refresh the current page
- 'web_search': Search the query in the current tab, the query should be a search query like humans search in web, concrete and not vague or super long. More the single most important items.

Element Interaction:
- 'click_element': Click an element by index
- 'input_text': Input text into a form element
- 'scroll_down'/'scroll_up': Scroll the page (with optional pixel amount)
- 'scroll_to_text': If you dont find something which you want to interact with, scroll to it
- 'send_keys': Send strings of special keys like Escape,Backspace, Insert, PageDown, Delete, Enter, Shortcuts such as `Control+o`, `Control+Shift+T` are supported as well. This gets used in keyboard.press.
- 'get_dropdown_options': Get all options from a dropdown
- 'select_dropdown_option': Select dropdown option for interactive element index by the text of the option you want to select

Content Extraction:
- 'extract_content': Extract page content to retrieve specific information from the page, e.g. all company names, a specifc description, all information about, links with companies in structured format or simply links

Tab Management:
- 'switch_tab': Switch to a specific tab
- 'open_tab': Open a new tab with a URL
- 'close_tab': Close the current tab

Utility:
- 'wait': Wait for a specified number of seconds
"""

Context = TypeVar("Context")


class BrowserUseTool(BaseTool, Generic[Context]):
    name: str = "browser_use"
    description: str = _BROWSER_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "go_to_url",
                    "click_element",
                    "input_text",
                    "scroll_down",
                    "scroll_up",
                    "scroll_to_text",
                    "send_keys",
                    "get_dropdown_options",
                    "select_dropdown_option",
                    "go_back",
                    "web_search",
                    "wait",
                    "extract_content",
                    "switch_tab",
                    "open_tab",
                    "close_tab",
                ],
                "description": "The browser action to perform",
            },
            "url": {
                "type": "string",
                "description": "URL for 'go_to_url' or 'open_tab' actions",
            },
            "index": {
                "type": "integer",
                "description": "Element index for 'click_element', 'input_text', 'get_dropdown_options', or 'select_dropdown_option' actions",
            },
            "text": {
                "type": "string",
                "description": "Text for 'input_text', 'scroll_to_text', or 'select_dropdown_option' actions",
            },
            "scroll_amount": {
                "type": "integer",
                "description": "Pixels to scroll (positive for down, negative for up) for 'scroll_down' or 'scroll_up' actions",
            },
            "tab_id": {
                "type": "integer",
                "description": "Tab ID for 'switch_tab' action",
            },
            "query": {
                "type": "string",
                "description": "Search query for 'web_search' action",
            },
            "goal": {
                "type": "string",
                "description": "Extraction goal for 'extract_content' action",
            },
            "keys": {
                "type": "string",
                "description": "Keys to send for 'send_keys' action",
            },
            "seconds": {
                "type": "integer",
                "description": "Seconds to wait for 'wait' action",
            },
        },
        "required": ["action"],
        "dependencies": {
            "go_to_url": ["url"],
            "click_element": ["index"],
            "input_text": ["index", "text"],
            "switch_tab": ["tab_id"],
            "open_tab": ["url"],
            "scroll_down": ["scroll_amount"],
            "scroll_up": ["scroll_amount"],
            "scroll_to_text": ["text"],
            "send_keys": ["keys"],
            "get_dropdown_options": ["index"],
            "select_dropdown_option": ["index", "text"],
            "go_back": [],
            "web_search": ["query"],
            "wait": ["seconds"],
            "extract_content": ["goal"],
        },
    }

    lock: asyncio.Lock = Field(default_factory=asyncio.Lock)
    browser: Optional[BrowserUseBrowser] = Field(default=None, exclude=True)
    context: Optional[BrowserContext] = Field(default=None, exclude=True)
    dom_service: Optional[DomService] = Field(default=None, exclude=True)
    web_search_tool: WebSearch = Field(default_factory=WebSearch, exclude=True)
    extracted_content_cache: dict = Field(default_factory=dict, exclude=True)  # Cache for extracted content

    # Context for generic functionality
    tool_context: Optional[Context] = Field(default=None, exclude=True)

    # Remove default_factory for LLM, it will be passed in __init__
    llm: Optional[LLM] = None # Change from Field(default_factory=LLM)

    def __init__(self, llm: Optional[LLM] = None, **data: Any):
        super().__init__(**data)
        if llm:
            self.llm = llm

    @field_validator("parameters", mode="before")
    def validate_parameters(cls, v: dict, info: ValidationInfo) -> dict:
        if not v:
            raise ValueError("Parameters cannot be empty")
        return v

    async def _ensure_browser_initialized(self) -> BrowserContext:
        """Ensure browser and context are initialized."""
        if self.browser is None:
            browser_config_kwargs = {"headless": False, "disable_security": True}

            if config.browser_config:
                from browser_use.browser.browser import ProxySettings

                # handle proxy settings.
                if config.browser_config.proxy and config.browser_config.proxy.server:
                    browser_config_kwargs["proxy"] = ProxySettings(
                        server=config.browser_config.proxy.server,
                        username=config.browser_config.proxy.username,
                        password=config.browser_config.proxy.password,
                    )

                browser_attrs = [
                    "headless",
                    "disable_security",
                    "extra_chromium_args",
                    "chrome_instance_path",
                    "wss_url",
                    "cdp_url",
                ]

                for attr in browser_attrs:
                    value = getattr(config.browser_config, attr, None)
                    if value is not None:
                        if not isinstance(value, list) or value:
                            browser_config_kwargs[attr] = value

            self.browser = BrowserUseBrowser(BrowserConfig(**browser_config_kwargs))

        if self.context is None:
            context_config = BrowserContextConfig()

            # if there is context config in the config, use it.
            if (
                config.browser_config
                and hasattr(config.browser_config, "new_context_config")
                and config.browser_config.new_context_config
            ):
                context_config = config.browser_config.new_context_config

            self.context = await self.browser.new_context(context_config)
            self.dom_service = DomService(await self.context.get_current_page())

        return self.context

    async def scroll_to_bottom_and_get_content(self, page) -> str:
        """Scroll through the page to ensure all content is loaded, then extract text."""
        try:
            # First, get initial content length
            initial_length = await page.evaluate("document.body.scrollHeight")
            
            # Scroll down multiple times to load dynamic content
            for i in range(5):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)  # Wait for content to load
                
                # Check if page height has changed (indicating more content loaded)
                new_length = await page.evaluate("document.body.scrollHeight")
                if new_length == initial_length:
                    break  # No more content loading
                initial_length = new_length
            
            # Scroll back to top for consistent state
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
            
            # Extract all visible text content
            content = await page.evaluate("""
                () => {
                    // Remove script and style elements
                    const scripts = document.querySelectorAll('script, style, nav, header, footer');
                    scripts.forEach(el => el.remove());
                    
                    // Get the main content
                    const main = document.querySelector('main, [role="main"], .content, #content, article');
                    if (main) {
                        return main.innerText;
                    }
                    
                    // Fallback to body content
                    return document.body.innerText;
                }
            """)
            
            return content or ""
            
        except Exception as e:
            logging.error(f"Error during scroll and content extraction: {e}")
            # Fallback to simple content extraction
            try:
                return await page.evaluate("document.body.innerText") or ""
            except:
                return ""

    async def extract_content_with_llm(self, content: str, goal: str, current_url: str) -> dict:
        """Extract content using LLM if available, otherwise use fallback method."""
        
        if not self.llm:
            # Fallback: return raw content with basic structure
            logging.warning("No LLM available for content extraction, using fallback method")
            return {
                "text": f"Content extracted from page (no LLM processing):\n{content[:2000]}{'...' if len(content) > 2000 else ''}",
                "metadata": {
                    "source": current_url,
                    "extraction_method": "fallback_no_llm",
                    "content_length": len(content)
                }
            }

        try:
            # Create prompt for LLM
            prompt_text = f"""
Your task is to extract the content of the page. You will be given a page and a goal, and you should extract all relevant information around this goal from the page. Respond in json format.

IMPORTANT:
1. Only extract information that is ACTUALLY PRESENT on the page. DO NOT make up or hallucinate any information.
2. Look for important content in headings, tables, lists, and main content sections.
3. Extract all relevant factual information as completely and accurately as possible.
4. If you cannot find information related to the goal, state that the information is not available.

Extraction goal: {goal}

Page content:
{content[:50000]}  # Limit content to avoid token limits
"""

            # Create message for LLM
            from app.schema import Message
            messages = [Message.user_message(prompt_text)]

            # Define extraction function
            extraction_function = {
                "type": "function",
                "function": {
                    "name": "extract_content",
                    "description": "Extract specific information from a webpage based on a goal",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "extracted_content": {
                                "type": "object",
                                "description": "The content extracted from the page according to the goal",
                                "properties": {
                                    "text": {
                                        "type": "string",
                                        "description": "Text content extracted from the page",
                                    },
                                    "metadata": {
                                        "type": "object",
                                        "description": "Additional metadata about the extracted content",
                                        "properties": {
                                            "source": {
                                                "type": "string",
                                                "description": "Source of the extracted content",
                                            }
                                        },
                                    },
                                },
                            }
                        },
                        "required": ["extracted_content"],
                    },
                },
            }

            # Use LLM to extract content
            response = await self.llm.ask_tool(
                messages,
                tools=[extraction_function],
                tool_choice="required",
            )

            if response and response.tool_calls and len(response.tool_calls) > 0:
                tool_call = response.tool_calls[0]
                try:
                    args = json.loads(tool_call.function.arguments)
                    extracted_content = args.get("extracted_content", {})

                    # Add source URL to metadata if not present
                    if not isinstance(extracted_content.get("metadata"), dict):
                        extracted_content["metadata"] = {}
                    if "source" not in extracted_content["metadata"]:
                        extracted_content["metadata"]["source"] = current_url
                    
                    extracted_content["metadata"]["extraction_method"] = "llm"
                    
                    return extracted_content

                except json.JSONDecodeError as e:
                    logging.error(f"Error parsing LLM extraction result: {e}")
                    # Fallback to simple extraction
                    pass

            # If LLM extraction failed, use fallback
            logging.warning("LLM extraction failed, using fallback")
            
        except Exception as e:
            logging.error(f"LLM extraction error: {e}")

        # Fallback extraction
        return {
            "text": f"Content extracted from page:\n{content[:2000]}{'...' if len(content) > 2000 else ''}",
            "metadata": {
                "source": current_url,
                "extraction_method": "fallback_after_llm_failure",
                "content_length": len(content)
            }
        }

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        index: Optional[int] = None,
        text: Optional[str] = None,
        scroll_amount: Optional[int] = None,
        tab_id: Optional[int] = None,
        query: Optional[str] = None,
        goal: Optional[str] = None,
        keys: Optional[str] = None,
        seconds: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        """
        Execute a specified browser action.

        Args:
            action: The browser action to perform
            url: URL for navigation or new tab
            index: Element index for click or input actions
            text: Text for input action or search query
            scroll_amount: Pixels to scroll for scroll action
            tab_id: Tab ID for switch_tab action
            query: Search query for Google search
            goal: Extraction goal for content extraction
            keys: Keys to send for keyboard actions
            seconds: Seconds to wait
            **kwargs: Additional arguments

        Returns:
            ToolResult with the action's output or error
        """
        async with self.lock:
            try:
                context = await self._ensure_browser_initialized()

                # Get max content length from config
                max_content_length = getattr(
                    config.browser_config, "max_content_length", 2000
                )

                # Navigation actions
                if action == "go_to_url":
                    if not url:
                        return ToolResult(
                            error="URL is required for 'go_to_url' action"
                        )
                    page = await context.get_current_page()
                    await page.goto(url)
                    await page.wait_for_load_state()
                    # Clear cache when navigating to new URL
                    self.extracted_content_cache.clear()
                    return ToolResult(output=f"Navigated to {url}")

                elif action == "go_back":
                    await context.go_back()
                    # Clear cache when going back
                    self.extracted_content_cache.clear()
                    return ToolResult(output="Navigated back")

                elif action == "refresh":
                    await context.refresh_page()
                    # Clear cache on refresh
                    self.extracted_content_cache.clear()
                    return ToolResult(output="Refreshed current page")

                elif action == "web_search":
                    if not query:
                        return ToolResult(
                            error="Query is required for 'web_search' action"
                        )
                    search_results = await self.web_search_tool.execute(query)

                    if search_results:
                        # Navigate to the first search result
                        first_result = search_results[0]
                        if isinstance(first_result, dict) and "url" in first_result:
                            url_to_navigate = first_result["url"]
                        elif isinstance(first_result, str):
                            url_to_navigate = first_result
                        else:
                            return ToolResult(
                                error=f"Invalid search result format: {first_result}"
                            )

                        page = await context.get_current_page()
                        await page.goto(url_to_navigate)
                        await page.wait_for_load_state()
                        # Clear cache when navigating to new URL
                        self.extracted_content_cache.clear()

                        return ToolResult(
                            output=f"Searched for '{query}' and navigated to first result: {url_to_navigate}\nAll results:"
                            + "\n".join([str(r) for r in search_results])
                        )
                    else:
                        return ToolResult(
                            error=f"No search results found for '{query}'"
                        )

                # Element interaction actions
                elif action == "click_element":
                    if index is None:
                        return ToolResult(
                            error="Index is required for 'click_element' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    download_path = await context._click_element_node(element)
                    output = f"Clicked element at index {index}"
                    if download_path:
                        output += f" - Downloaded file to {download_path}"
                    return ToolResult(output=output)

                elif action == "input_text":
                    if index is None or not text:
                        return ToolResult(
                            error="Index and text are required for 'input_text' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    await context._input_text_element_node(element, text)
                    return ToolResult(
                        output=f"Input '{text}' into element at index {index}"
                    )

                elif action == "scroll_down" or action == "scroll_up":
                    direction = 1 if action == "scroll_down" else -1
                    amount = (
                        scroll_amount
                        if scroll_amount is not None
                        else context.config.browser_window_size["height"]
                    )
                    await context.execute_javascript(
                        f"window.scrollBy(0, {direction * amount});"
                    )
                    return ToolResult(
                        output=f"Scrolled {'down' if direction > 0 else 'up'} by {amount} pixels"
                    )

                elif action == "scroll_to_text":
                    if not text:
                        return ToolResult(
                            error="Text is required for 'scroll_to_text' action"
                        )
                    page = await context.get_current_page()
                    try:
                        locator = page.get_by_text(text, exact=False)
                        await locator.scroll_into_view_if_needed()
                        return ToolResult(output=f"Scrolled to text: '{text}'")
                    except Exception as e:
                        return ToolResult(error=f"Failed to scroll to text: {str(e)}")

                elif action == "send_keys":
                    if not keys:
                        return ToolResult(
                            error="Keys are required for 'send_keys' action"
                        )
                    page = await context.get_current_page()
                    await page.keyboard.press(keys)
                    return ToolResult(output=f"Sent keys: {keys}")

                elif action == "get_dropdown_options":
                    if index is None:
                        return ToolResult(
                            error="Index is required for 'get_dropdown_options' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    page = await context.get_current_page()
                    options = await page.evaluate(
                        """
                        (xpath) => {
                            const select = document.evaluate(xpath, document, null,
                                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            if (!select) return null;
                            return Array.from(select.options).map(opt => ({
                                text: opt.text,
                                value: opt.value,
                                index: opt.index
                            }));
                        }
                    """,
                        element.xpath,
                    )
                    return ToolResult(output=f"Dropdown options: {options}")

                elif action == "select_dropdown_option":
                    if index is None or not text:
                        return ToolResult(
                            error="Index and text are required for 'select_dropdown_option' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    page = await context.get_current_page()
                    await page.select_option(element.xpath, label=text)
                    return ToolResult(
                        output=f"Selected option '{text}' from dropdown at index {index}"
                    )

                # Content extraction actions - FIXED VERSION
                elif action == "extract_content":
                    goal = goal or kwargs.get("goal")
                    if not goal:
                        return ToolResult(
                            error="Missing 'goal' parameter for extract_content action"
                        )

                    # Get the current page
                    page = await context.get_current_page()
                    current_url = page.url

                    # Check cache first
                    cache_key = f"{goal}:{current_url}"
                    cached_result = self.extracted_content_cache.get(cache_key)
                    if cached_result:
                        logging.info(f"Returning cached extraction for {cache_key}")
                        return ToolResult(output=cached_result)

                    try:
                        # Scroll through page and extract content
                        content = await self.scroll_to_bottom_and_get_content(page)
                        
                        if not content or len(content.strip()) < 50:
                            # If we didn't get enough content, try alternative methods
                            try:
                                page_title = await page.title()
                                html_content = await page.content()
                                
                                # Try to extract text using markdownify if available
                                try:
                                    import markdownify
                                    content = markdownify.markdownify(
                                        html_content,
                                        heading_style="ATX",
                                        strip=["script", "style"]
                                    )
                                except ImportError:
                                    # Fallback: just get text content
                                    content = f"Page Title: {page_title}\n\nContent extraction failed. Page may require interaction to display content."
                            except Exception as e:
                                logging.error(f"Alternative content extraction failed: {e}")
                                content = "Content extraction failed."

                        # Extract content using LLM if available, otherwise use fallback
                        extracted_content = await self.extract_content_with_llm(content, goal, current_url)
                        
                        # Format as JSON
                        content_json = json.dumps(extracted_content, indent=2, ensure_ascii=False)
                        msg = f"Extracted from page:\n{content_json}\n"

                        # Cache the result
                        self.extracted_content_cache[cache_key] = msg
                        
                        return ToolResult(output=msg)

                    except Exception as e:
                        error_msg = f"Failed to extract content: {str(e)}"
                        logging.error(error_msg)
                        
                        # Emergency fallback
                        try:
                            page_title = await page.title()
                            emergency_content = {
                                "text": f"Page title: {page_title}\nError occurred during extraction: {str(e)}",
                                "metadata": {
                                    "source": current_url,
                                    "extraction_method": "emergency"
                                }
                            }
                            emergency_json = json.dumps(emergency_content, indent=2, ensure_ascii=False)
                            return ToolResult(output=f"Extracted from page:\n{emergency_json}\n")
                        except:
                            return ToolResult(error=error_msg)

                # Tab management actions
                elif action == "switch_tab":
                    if tab_id is None:
                        return ToolResult(
                            error="Tab ID is required for 'switch_tab' action"
                        )
                    await context.switch_to_tab(tab_id)
                    page = await context.get_current_page()
                    await page.wait_for_load_state()
                    return ToolResult(output=f"Switched to tab {tab_id}")

                elif action == "open_tab":
                    if not url:
                        return ToolResult(error="URL is required for 'open_tab' action")
                    await context.create_new_tab(url)
                    return ToolResult(output=f"Opened new tab with {url}")

                elif action == "close_tab":
                    await context.close_current_tab()
                    return ToolResult(output="Closed current tab")

                # Utility actions
                elif action == "wait":
                    seconds_to_wait = seconds if seconds is not None else 3
                    await asyncio.sleep(seconds_to_wait)
                    return ToolResult(output=f"Waited for {seconds_to_wait} seconds")

                else:
                    return ToolResult(error=f"Unknown action: {action}")

            except Exception as e:
                return ToolResult(error=f"Browser action '{action}' failed: {str(e)}")

    async def get_current_state(
        self, context: Optional[BrowserContext] = None
    ) -> ToolResult:
        """
        Get the current browser state as a ToolResult.
        If context is not provided, uses self.context.
        """
        try:
            # Use provided context or fall back to self.context
            ctx = context or self.context
            if not ctx:
                return ToolResult(error="Browser context not initialized")

            state = await ctx.get_state()

            # Create a viewport_info dictionary if it doesn't exist
            viewport_height = 0
            if hasattr(state, "viewport_info") and state.viewport_info:
                viewport_height = state.viewport_info.height
            elif hasattr(ctx, "config") and hasattr(ctx.config, "browser_window_size"):
                viewport_height = ctx.config.browser_window_size.get("height", 0)

            # Take a screenshot for the state
            page = await ctx.get_current_page()

            await page.bring_to_front()
            await page.wait_for_load_state()

            screenshot = await page.screenshot(
                full_page=True, animations="disabled", type="jpeg", quality=100
            )

            screenshot = base64.b64encode(screenshot).decode("utf-8")

            # Build the state info with all required fields
            state_info = {
                "url": state.url,
                "title": state.title,
                "tabs": [tab.model_dump() for tab in state.tabs],
                "help": "[0], [1], [2], etc., represent clickable indices corresponding to the elements listed. Clicking on these indices will navigate to or interact with the respective content behind them.",
                "interactive_elements": (
                    state.element_tree.clickable_elements_to_string()
                    if state.element_tree
                    else ""
                ),
                "scroll_info": {
                    "pixels_above": getattr(state, "pixels_above", 0),
                    "pixels_below": getattr(state, "pixels_below", 0),
                    "total_height": getattr(state, "pixels_above", 0)
                    + getattr(state, "pixels_below", 0)
                    + viewport_height,
                },
                "viewport_height": viewport_height,
            }

            return ToolResult(
                output=json.dumps(state_info, indent=4, ensure_ascii=False),
                base64_image=screenshot,
            )
        except Exception as e:
            return ToolResult(error=f"Failed to get browser state: {str(e)}")

    async def cleanup(self):
        """Clean up browser resources."""
        async with self.lock:
            if self.context is not None:
                await self.context.close()
                self.context = None
                self.dom_service = None
            if self.browser is not None:
                await self.browser.close()
                self.browser = None

    def __del__(self):
        """Cleanup method for BrowserUseTool"""
        try:
            # Check if attributes exist before accessing them
            if hasattr(self, 'browser') and self.browser is not None:
                # Add browser cleanup logic here
                pass
            if hasattr(self, 'context') and self.context is not None:
                # Add context cleanup logic here
                pass
        except Exception:
            # Ignore all errors during cleanup
            pass

    @classmethod
    def create_with_context(cls, context: Context) -> "BrowserUseTool[Context]":
        """Factory method to create a BrowserUseTool with a specific context."""
        tool = cls()
        tool.tool_context = context
        return tool