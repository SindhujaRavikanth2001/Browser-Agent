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
    extracted_content_cache: dict = Field(default_factory=dict, exclude=True)
    
    # Track extraction state per URL
    extraction_state: dict = Field(default_factory=dict, exclude=True)

    # Context for generic functionality
    tool_context: Optional[Context] = Field(default=None, exclude=True)

    # LLM instance
    llm: Optional[LLM] = None

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

    async def extract_complete_content_with_beautifulsoup(self, current_url: str, goal: str) -> dict:
        """Extract complete content using BeautifulSoup with progressive scrolling and comprehensive extraction."""
        try:
            import requests
            from bs4 import BeautifulSoup
            from requests.exceptions import RequestException
            
            logging.info(f"Starting comprehensive BeautifulSoup extraction from: {current_url}")
            
            # Set up headers to mimic a real browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            # Multiple attempts with different methods
            content_text = None
            method_used = "unknown"
            
            # Method 1: Standard requests
            try:
                logging.info("Attempting Method 1: Standard requests")
                response = requests.get(current_url, headers=headers, timeout=30)
                response.raise_for_status()
                content_text = response.text
                method_used = "requests"
                logging.info(f"Method 1 successful: Retrieved {len(content_text)} characters")
            except Exception as e:
                logging.warning(f"Method 1 failed: {e}")
            
            # Method 2: Try with session and cookies
            if not content_text:
                try:
                    logging.info("Attempting Method 2: Session with cookies")
                    session = requests.Session()
                    session.headers.update(headers)
                    response = session.get(current_url, timeout=30)
                    response.raise_for_status()
                    content_text = response.text
                    method_used = "session_requests"
                    logging.info(f"Method 2 successful: Retrieved {len(content_text)} characters")
                except Exception as e:
                    logging.warning(f"Method 2 failed: {e}")
            
            # Method 3: Browser-based extraction (fallback)
            if not content_text:
                try:
                    logging.info("Attempting Method 3: Browser-based extraction")
                    context = await self._ensure_browser_initialized()
                    page = await context.get_current_page()
                    
                    # Ensure we're on the right page
                    if page.url != current_url:
                        await page.goto(current_url)
                        await page.wait_for_load_state('networkidle')
                    
                    # Progressive scrolling to load all content
                    await self.progressive_scroll_and_load(page)
                    content_text = await page.content()
                    method_used = "browser"
                    logging.info(f"Method 3 successful: Retrieved {len(content_text)} characters")
                except Exception as e:
                    logging.error(f"Method 3 failed: {e}")
                    return {
                        'error': f"All extraction methods failed. Last error: {str(e)}",
                        'metadata': {
                            'source': current_url,
                            'extraction_method': 'all_methods_failed'
                        }
                    }
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(content_text, 'html.parser')
            
            # Remove unwanted elements
            for element in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
                element.decompose()
            
            # Extract comprehensive structured content
            extracted_data = {
                'title': '',
                'main_content': [],
                'headings': [],
                'paragraphs': [],
                'lists': [],
                'sections': [],
                'raw_text': '',
                'metadata': {}
            }
            
            # Get title
            title_elem = soup.find('title')
            if title_elem:
                extracted_data['title'] = title_elem.get_text(strip=True)
            
            # Find main content area with multiple strategies
            main_content = None
            main_selectors = [
                'main', 'article', '[role="main"]', 
                '.main-content', '.content', '.post-content', '.entry-content',
                '#main-content', '#content', '#main', '.main', '.article-content',
                '.page-content', '.body-content'
            ]
            
            for selector in main_selectors:
                main_content = soup.select_one(selector)
                if main_content:
                    logging.info(f"Found main content using selector: {selector}")
                    break
            
            # If no main content found, use body
            if not main_content:
                main_content = soup.find('body')
                logging.info("Using body as main content container")
            
            if main_content:
                # Extract headings with hierarchy
                for heading in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    heading_text = heading.get_text(strip=True)
                    if heading_text:
                        extracted_data['headings'].append({
                            'level': heading.name,
                            'text': heading_text,
                            'id': heading.get('id', ''),
                            'class': heading.get('class', [])
                        })
                
                # Extract paragraphs with filtering
                for p in main_content.find_all('p'):
                    p_text = p.get_text(strip=True)
                    if p_text and len(p_text) > 15:  # Filter out very short paragraphs
                        extracted_data['paragraphs'].append(p_text)
                
                # Extract lists comprehensively
                for ul in main_content.find_all(['ul', 'ol']):
                    list_items = []
                    for li in ul.find_all('li'):
                        li_text = li.get_text(strip=True)
                        if li_text:
                            list_items.append(li_text)
                    if list_items:
                        extracted_data['lists'].append({
                            'type': ul.name,
                            'items': list_items,
                            'class': ul.get('class', [])
                        })
                
                # Extract sections
                for section in main_content.find_all(['section', 'div']):
                    section_text = section.get_text(strip=True)
                    if section_text and len(section_text) > 50:
                        section_class = section.get('class', [])
                        section_id = section.get('id', '')
                        if section_class or section_id:  # Only capture sections with identifiers
                            extracted_data['sections'].append({
                                'text': section_text[:500] + ('...' if len(section_text) > 500 else ''),
                                'class': section_class,
                                'id': section_id
                            })
                
                # Get complete clean text content
                extracted_data['raw_text'] = main_content.get_text(separator='\n', strip=True)
            
            # Create comprehensive structured content for LLM processing
            structured_content = f"""
DOCUMENT TITLE: {extracted_data['title']}

HEADINGS STRUCTURE:
{chr(10).join([f"{h['level'].upper()}: {h['text']}" for h in extracted_data['headings']])}

MAIN CONTENT PARAGRAPHS:
{chr(10).join(extracted_data['paragraphs'])}

STRUCTURED LISTS:
{chr(10).join([f"{lst['type'].upper()}: {chr(10).join([f'  - {item}' for item in lst['items']])}" for lst in extracted_data['lists']])}

COMPLETE DOCUMENT TEXT:
{extracted_data['raw_text']}
"""
            
            logging.info(f"BeautifulSoup extraction complete: {len(extracted_data['paragraphs'])} paragraphs, {len(extracted_data['headings'])} headings, {len(extracted_data['lists'])} lists")
            
            # Process with LLM if available
            if self.llm:
                llm_result = await self.process_with_llm_comprehensive(structured_content, goal, current_url)
                return {
                    'raw_extraction': extracted_data,
                    'structured_content': structured_content,
                    'llm_processed': llm_result,
                    'metadata': {
                        'source': current_url,
                        'extraction_method': f'beautifulsoup_{method_used}_with_llm',
                        'content_length': len(structured_content),
                        'paragraphs_found': len(extracted_data['paragraphs']),
                        'headings_found': len(extracted_data['headings']),
                        'lists_found': len(extracted_data['lists'])
                    }
                }
            else:
                return {
                    'raw_extraction': extracted_data,
                    'structured_content': structured_content,
                    'metadata': {
                        'source': current_url,
                        'extraction_method': f'beautifulsoup_{method_used}_only',
                        'content_length': len(structured_content),
                        'paragraphs_found': len(extracted_data['paragraphs']),
                        'headings_found': len(extracted_data['headings']),
                        'lists_found': len(extracted_data['lists'])
                    }
                }
                
        except Exception as e:
            logging.error(f"BeautifulSoup extraction failed: {e}")
            return {
                'error': f"BeautifulSoup extraction failed: {str(e)}",
                'metadata': {
                    'source': current_url,
                    'extraction_method': 'beautifulsoup_failed'
                }
            }

    async def progressive_scroll_and_load(self, page):
        """Progressive scrolling to ensure all content is loaded."""
        try:
            logging.info("Starting progressive scroll to load complete content")
            
            # Get initial scroll height
            initial_height = await page.evaluate("document.body.scrollHeight")
            logging.info(f"Initial page height: {initial_height}")
            
            # Progressive scrolling
            scroll_step = 1000  # Pixels per scroll
            current_position = 0
            max_scrolls = 20  # Prevent infinite scrolling
            scroll_count = 0
            
            while scroll_count < max_scrolls:
                # Scroll down
                await page.evaluate(f"window.scrollTo(0, {current_position + scroll_step})")
                await asyncio.sleep(0.5)  # Wait for content to load
                
                # Check if we've reached the bottom
                new_height = await page.evaluate("document.body.scrollHeight")
                current_position = await page.evaluate("window.pageYOffset")
                
                if current_position + await page.evaluate("window.innerHeight") >= new_height:
                    logging.info(f"Reached bottom of page at position {current_position}")
                    break
                
                current_position += scroll_step
                scroll_count += 1
                
                # Check for lazy-loaded content
                if new_height > initial_height:
                    logging.info(f"New content loaded, height increased to {new_height}")
                    initial_height = new_height
            
            # Scroll back to top for consistent state
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
            
            logging.info(f"Progressive scrolling completed after {scroll_count} scrolls")
            
        except Exception as e:
            logging.error(f"Error during progressive scrolling: {e}")

    async def process_with_llm_comprehensive(self, content: str, goal: str, current_url: str) -> dict:
        """Process extracted content with LLM comprehensively to address the user's goal."""
        try:
            # Enhanced prompt that focuses on completeness
            prompt_text = f"""
You are an expert content analyzer with a focus on completeness and accuracy. You have been given comprehensive webpage content and a specific goal.

GOAL: {goal}

COMPREHENSIVE WEBPAGE CONTENT:
{content[:25000]}  # Use more content, up to 25k characters

CRITICAL INSTRUCTIONS:
1. READ THE ENTIRE CONTENT CAREFULLY - Do not rush through it
2. First, provide a thorough summary of ALL key points from the webpage
3. Then, directly and completely address the user's specific goal
4. If the goal involves creating something (like survey questions), provide a COMPLETE, well-structured response
5. Ensure your response is comprehensive and actionable
6. Double-check that you haven't cut off any important information

RESPONSE FORMAT:
Please provide your response as a complete, well-formatted answer that fully addresses the goal. If creating survey questions, ensure all questions are complete and properly formatted.

Start your response now:
"""

            from app.schema import Message
            messages = [Message.user_message(prompt_text)]

            # Use LLM to process content and address the goal
            response = await self.llm.ask(messages)
            
            if response:
                return {
                    'content_summary': 'LLM processed the complete content',
                    'goal_response': response,
                    'full_llm_response': response,
                    'processing_method': 'comprehensive_llm_processing'
                }
            else:
                return {
                    'error': 'No response from LLM',
                    'content_summary': '',
                    'goal_response': '',
                    'full_llm_response': ''
                }
                
        except Exception as e:
            logging.error(f"LLM processing error: {e}")
            return {
                'error': f"LLM processing failed: {str(e)}",
                'content_summary': '',
                'goal_response': '',
                'full_llm_response': ''
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
        """Execute a specified browser action."""
        async with self.lock:
            try:
                context = await self._ensure_browser_initialized()

                # Navigation actions
                if action == "go_to_url":
                    if not url:
                        return ToolResult(error="URL is required for 'go_to_url' action")
                    page = await context.get_current_page()
                    await page.goto(url)
                    await page.wait_for_load_state('networkidle')  # Wait for network to be idle
                    self.extracted_content_cache.clear()
                    self.extraction_state.clear()  # Clear extraction state
                    return ToolResult(output=f"Navigated to {url}")

                elif action == "go_back":
                    await context.go_back()
                    self.extracted_content_cache.clear()
                    self.extraction_state.clear()
                    return ToolResult(output="Navigated back")

                elif action == "refresh":
                    await context.refresh_page()
                    self.extracted_content_cache.clear()
                    self.extraction_state.clear()
                    return ToolResult(output="Refreshed current page")

                elif action == "web_search":
                    if not query:
                        return ToolResult(error="Query is required for 'web_search' action")
                    search_results = await self.web_search_tool.execute(query)

                    if search_results:
                        first_result = search_results[0]
                        if isinstance(first_result, dict) and "url" in first_result:
                            url_to_navigate = first_result["url"]
                        elif isinstance(first_result, str):
                            url_to_navigate = first_result
                        else:
                            return ToolResult(error=f"Invalid search result format: {first_result}")

                        page = await context.get_current_page()
                        await page.goto(url_to_navigate)
                        await page.wait_for_load_state('networkidle')
                        self.extracted_content_cache.clear()
                        self.extraction_state.clear()

                        return ToolResult(
                            output=f"Searched for '{query}' and navigated to first result: {url_to_navigate}\nAll results:" +
                            "\n".join([str(r) for r in search_results])
                        )
                    else:
                        return ToolResult(error=f"No search results found for '{query}'")

                # Element interaction actions
                elif action == "click_element":
                    if index is None:
                        return ToolResult(error="Index is required for 'click_element' action")
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
                        return ToolResult(error="Index and text are required for 'input_text' action")
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    await context._input_text_element_node(element, text)
                    return ToolResult(output=f"Input '{text}' into element at index {index}")

                elif action == "scroll_down" or action == "scroll_up":
                    direction = 1 if action == "scroll_down" else -1
                    amount = (
                        scroll_amount if scroll_amount is not None 
                        else context.config.browser_window_size["height"]
                    )
                    await context.execute_javascript(f"window.scrollBy(0, {direction * amount});")
                    return ToolResult(
                        output=f"Scrolled {'down' if direction > 0 else 'up'} by {amount} pixels"
                    )

                elif action == "scroll_to_text":
                    if not text:
                        return ToolResult(error="Text is required for 'scroll_to_text' action")
                    page = await context.get_current_page()
                    try:
                        locator = page.get_by_text(text, exact=False)
                        await locator.scroll_into_view_if_needed()
                        return ToolResult(output=f"Scrolled to text: '{text}'")
                    except Exception as e:
                        return ToolResult(error=f"Failed to scroll to text: {str(e)}")

                elif action == "send_keys":
                    if not keys:
                        return ToolResult(error="Keys are required for 'send_keys' action")
                    page = await context.get_current_page()
                    await page.keyboard.press(keys)
                    return ToolResult(output=f"Sent keys: {keys}")

                elif action == "get_dropdown_options":
                    if index is None:
                        return ToolResult(error="Index is required for 'get_dropdown_options' action")
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
                        return ToolResult(error="Index and text are required for 'select_dropdown_option' action")
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    page = await context.get_current_page()
                    await page.select_option(element.xpath, label=text)
                    return ToolResult(output=f"Selected option '{text}' from dropdown at index {index}")

                # Enhanced comprehensive content extraction
                elif action == "extract_content":
                    goal = goal or kwargs.get("goal")
                    if not goal:
                        return ToolResult(error="Missing 'goal' parameter for extract_content action")

                    page = await context.get_current_page()
                    current_url = page.url

                    # Check if we've already extracted content for this URL+goal combination
                    cache_key = f"{goal}:{current_url}"
                    
                    # Always do fresh extraction to avoid partial content issues
                    logging.info(f"Starting fresh comprehensive extraction for {cache_key}")

                    try:
                        # Use comprehensive BeautifulSoup extraction method
                        extraction_result = await self.extract_complete_content_with_beautifulsoup(current_url, goal)
                        
                        # Format the comprehensive result with better structure
                        if 'llm_processed' in extraction_result:
                            llm_data = extraction_result['llm_processed']
                            
                            output_message = f"""
=== COMPREHENSIVE CONTENT EXTRACTION AND ANALYSIS ===

EXTRACTION METADATA:
Source: {extraction_result.get('metadata', {}).get('source', current_url)}
Method: {extraction_result.get('metadata', {}).get('extraction_method', 'Unknown')}
Content Length: {extraction_result.get('metadata', {}).get('content_length', 0)} characters
Paragraphs Found: {extraction_result.get('metadata', {}).get('paragraphs_found', 0)}
Headings Found: {extraction_result.get('metadata', {}).get('headings_found', 0)}
Lists Found: {extraction_result.get('metadata', {}).get('lists_found', 0)}

=== DOCUMENT TITLE ===
{extraction_result.get('raw_extraction', {}).get('title', 'N/A')}

=== COMPLETE STRUCTURED CONTENT (FULL - NO TRUNCATION) ===
{extraction_result.get('structured_content', 'No structured content available')}

=== LLM COMPREHENSIVE ANALYSIS ===
{llm_data.get('goal_response', 'No goal response available')}

=== PROCESSING DETAILS ===
Processing Method: {llm_data.get('processing_method', 'Unknown')}
Response Type: Complete LLM Analysis

=== FULL RAW EXTRACTION DATA (FOR REFERENCE) ===
Headings Structure:
{chr(10).join([f"  {h.get('level', 'unknown').upper()}: {h.get('text', '')}" for h in extraction_result.get('raw_extraction', {}).get('headings', [])])}

Total Paragraphs: {len(extraction_result.get('raw_extraction', {}).get('paragraphs', []))}
Total Lists: {len(extraction_result.get('raw_extraction', {}).get('lists', []))}
"""
                        else:
                            output_message = f"""
=== CONTENT EXTRACTION (BeautifulSoup Only) ===

EXTRACTION METADATA:
Source: {extraction_result.get('metadata', {}).get('source', current_url)}
Method: {extraction_result.get('metadata', {}).get('extraction_method', 'Unknown')}
Content Length: {extraction_result.get('metadata', {}).get('content_length', 0)} characters
Paragraphs Found: {extraction_result.get('metadata', {}).get('paragraphs_found', 0)}
Headings Found: {extraction_result.get('metadata', {}).get('headings_found', 0)}
Lists Found: {extraction_result.get('metadata', {}).get('lists_found', 0)}

=== DOCUMENT TITLE ===
{extraction_result.get('raw_extraction', {}).get('title', 'N/A')}

=== COMPLETE STRUCTURED CONTENT (FULL - NO TRUNCATION) ===
{extraction_result.get('structured_content', 'No structured content available')}

=== RAW EXTRACTION SUMMARY ===
Total Content Extracted: {len(extraction_result.get('raw_extraction', {}).get('raw_text', ''))} characters
Processing Status: BeautifulSoup extraction completed successfully
"""

                        # Cache the comprehensive result
                        self.extracted_content_cache[cache_key] = output_message
                        
                        return ToolResult(output=output_message)

                    except Exception as e:
                        error_msg = f"Failed to extract comprehensive content: {str(e)}"
                        logging.error(error_msg)
                        
                        # Emergency fallback with browser content
                        try:
                            page_title = await page.title()
                            # Try to get some content as fallback
                            await self.progressive_scroll_and_load(page)
                            page_content = await page.evaluate("document.body.innerText") or ""
                            
                            emergency_content = {
                                "title": page_title,
                                "content": page_content[:5000] + ('...' if len(page_content) > 5000 else ''),
                                "error": str(e),
                                "metadata": {
                                    "source": current_url,
                                    "extraction_method": "emergency_fallback"
                                }
                            }
                            
                            emergency_output = f"""
=== EMERGENCY CONTENT EXTRACTION ===

Title: {emergency_content['title']}
Source: {current_url}
Method: Emergency fallback after extraction failure

ERROR DETAILS:
{emergency_content['error']}

PARTIAL CONTENT RETRIEVED:
{emergency_content['content']}

Note: This is a partial extraction due to technical issues. Please try the extraction again or use alternative methods.
"""
                            return ToolResult(output=emergency_output)
                        except:
                            return ToolResult(error=error_msg)

                # Tab management actions
                elif action == "switch_tab":
                    if tab_id is None:
                        return ToolResult(error="Tab ID is required for 'switch_tab' action")
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

    async def get_current_state(self, context: Optional[BrowserContext] = None) -> ToolResult:
        """Get the current browser state as a ToolResult."""
        try:
            ctx = context or self.context
            if not ctx:
                return ToolResult(error="Browser context not initialized")

            state = await ctx.get_state()

            viewport_height = 0
            if hasattr(state, "viewport_info") and state.viewport_info:
                viewport_height = state.viewport_info.height
            elif hasattr(ctx, "config") and hasattr(ctx.config, "browser_window_size"):
                viewport_height = ctx.config.browser_window_size.get("height", 0)

            page = await ctx.get_current_page()
            await page.bring_to_front()
            await page.wait_for_load_state()

            screenshot = await page.screenshot(
                full_page=True, animations="disabled", type="jpeg", quality=100
            )
            screenshot = base64.b64encode(screenshot).decode("utf-8")

            state_info = {
                "url": state.url,
                "title": state.title,
                "tabs": [tab.model_dump() for tab in state.tabs],
                "help": "[0], [1], [2], etc., represent clickable indices corresponding to the elements listed.",
                "interactive_elements": (
                    state.element_tree.clickable_elements_to_string() if state.element_tree else ""
                ),
                "scroll_info": {
                    "pixels_above": getattr(state, "pixels_above", 0),
                    "pixels_below": getattr(state, "pixels_below", 0),
                    "total_height": getattr(state, "pixels_above", 0) + getattr(state, "pixels_below", 0) + viewport_height,
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
            if hasattr(self, 'browser') and self.browser is not None:
                pass
            if hasattr(self, 'context') and self.context is not None:
                pass
        except Exception:
            pass

    @classmethod
    def create_with_context(cls, context: Context) -> "BrowserUseTool[Context]":
        """Factory method to create a BrowserUseTool with a specific context."""
        tool = cls()
        tool.tool_context = context
        return tool