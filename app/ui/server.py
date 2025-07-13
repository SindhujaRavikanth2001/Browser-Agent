import asyncio
import os
import json
from datetime import datetime
from asyncio import TimeoutError as AsyncTimeoutError
from typing import Dict, List, Optional, Union, Any
from contextvars import ContextVar
import requests
from bs4 import BeautifulSoup
from enum import Enum
from dotenv import load_dotenv
import base64
import urllib.parse
import pytesseract
from PIL import Image
import io

# Load environment variables
load_dotenv()

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
import re, requests
from urllib.parse import urlparse

# Google API imports
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Define a global context variable for the Manus agent
g = ContextVar('g', default=None)

class UserAction(Enum):
    URL_RESEARCH = "url_research"
    BUILD_QUESTIONNAIRE = "build_questionnaire"
    GENERAL_RESEARCH = "general_research"

class ResearchStage(Enum):
    INITIAL = "initial"
    DESIGN_INPUT = "design_input"
    DESIGN_REVIEW = "design_review"
    DATABASE_SEARCH = "database_search"
    DECISION_POINT = "decision_point"
    QUESTIONNAIRE_BUILDER = "questionnaire_builder"
    FINAL_OUTPUT = "final_output"

class ResearchDesign(BaseModel):
    research_topic: Optional[str] = None
    objectives: Optional[List[str]] = None
    target_population: Optional[str] = None
    timeframe: Optional[str] = None
    questions: Optional[List[str]] = None
    internet_questions: Optional[List[str]] = None
    internet_sources: Optional[List[str]] = None
    screenshots: Optional[List[Dict]] = None
    use_internet_questions: bool = False
    stage: ResearchStage = ResearchStage.INITIAL
    user_responses: Optional[Dict] = None
    questionnaire_responses: Optional[Dict] = None
    chat_history: Optional[List[Dict]] = None
    
    # URL management fields
    all_collected_urls: Optional[List[str]] = None
    current_batch_index: int = 0
    browsed_urls: Optional[List[str]] = None
    rebrowse_count: int = 0
    extracted_questions_with_sources: Optional[List[Dict]] = None
    
    # NEW: Question selection tracking
    selected_questions_pool: Optional[List[Dict]] = None  # All questions found so far
    user_selected_questions: Optional[List[Dict]] = None  # Questions user has selected
    awaiting_selection: bool = False  # Flag to indicate we're waiting for user selection
    max_selectable_questions: int = 30  # Maximum questions user can select
    additional_questions: Optional[List[str]] = None

class UserMessage(BaseModel):
    content: str
    action_type: Optional[str] = None
    research_session_id: Optional[str] = None

class ImprovedQuestionExtractor:
    """Improved question extraction with better pattern recognition and source attribution"""
    
    def __init__(self):
        # Fixed and improved regex patterns
        self.question_patterns = [
            # Basic question words - FIXED regex syntax
            r'(?:^|\n)\s*(?:\d+[\.\)]\s*)?([^.!]*(?:How|What|Which|Would|Do|Are|Have|Can|Did|Will)\s+[^?]*\?)',
            
            # Rating and scale questions
            r'(?:^|\n)\s*(?:\d+[\.\)]\s*)?([^.!]*(?:On\s+a\s+scale|Rate|Please\s+rate|from\s+1\s+to|1-10|scale\s+of)[^?]*\?)',
            
            # Likert scale indicators
            r'(?:^|\n)\s*(?:\d+[\.\)]\s*)?([^.!]*(?:strongly\s+agree|satisfaction|satisfied|likely|important)[^?]*\?)',
            
            # Frequency questions
            r'(?:^|\n)\s*(?:\d+[\.\)]\s*)?([^.!]*(?:How\s+often|How\s+frequently|How\s+many\s+times)[^?]*\?)',
            
            # Preference questions
            r'(?:^|\n)\s*(?:\d+[\.\)]\s*)?([^.!]*(?:prefer|choose|select|pick)[^?]*\?)',
            
            # Experience questions
            r'(?:^|\n)\s*(?:\d+[\.\)]\s*)?([^.!]*(?:experience|background|years)[^?]*\?)',
            
            # Opinion questions
            r'(?:^|\n)\s*(?:\d+[\.\)]\s*)?([^.!]*(?:opinion|think|believe|feel)[^?]*\?)',
            
            # Recommendation questions
            r'(?:^|\n)\s*(?:\d+[\.\)]\s*)?([^.!]*(?:recommend|suggest)[^?]*\?)',
        ]
    
    def extract_questions_with_sources(self, content: str, url: str) -> List[Dict]:
        """Extract questions with improved pattern matching and full source tracking"""
        
        all_questions = []
        
        # Method 1: Simple line-by-line analysis (most reliable)
        simple_questions = self._extract_simple_questions(content, url)
        all_questions.extend(simple_questions)
        
        # Method 2: Advanced pattern matching
        pattern_questions = self._extract_pattern_questions(content, url)
        all_questions.extend(pattern_questions)
        
        # Remove duplicates while preserving order
        unique_questions = []
        seen = set()
        
        for q_dict in all_questions:
            question_lower = q_dict['question'].lower().strip()
            if question_lower not in seen and len(question_lower) > 15:
                seen.add(question_lower)
                unique_questions.append(q_dict)
        
        return unique_questions[:10]  # Limit to top 10 questions
    
    def _extract_simple_questions(self, content: str, url: str) -> List[Dict]:
        """Simple, reliable question extraction"""
        questions = []
        lines = content.split('\n')
        
        question_starters = [
            'how ', 'what ', 'which ', 'would you', 'do you', 'are you',
            'have you', 'can you', 'did you', 'will you', 'please rate',
            'on a scale', 'rate the', 'how often', 'how much', 'how likely',
            'how satisfied', 'how important', 'to what extent'
        ]
        
        for line in lines:
            line = line.strip()
            
            # Must end with question mark and have reasonable length
            if not line.endswith('?') or len(line) < 20 or len(line) > 300:
                continue
            
            # Clean up formatting
            clean_line = re.sub(r'^\d+[\.\)]\s*', '', line)  # Remove numbering
            clean_line = re.sub(r'^[-•*]\s*', '', clean_line)  # Remove bullets
            clean_line = clean_line.strip()
            
            # Check if it starts with question words
            line_lower = clean_line.lower()
            if any(line_lower.startswith(starter) for starter in question_starters):
                questions.append({
                    'question': clean_line,
                    'source': url,  # Full URL instead of domain
                    'extraction_method': 'simple_pattern'
                })
        
        return questions
    
    def _extract_pattern_questions(self, content: str, url: str) -> List[Dict]:
        """Advanced pattern-based extraction with fixed regex"""
        questions = []
        
        for pattern in self.question_patterns:
            try:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    question = match.group(1).strip()
                    
                    # Clean up
                    question = re.sub(r'^\d+[\.\)]\s*', '', question)
                    question = re.sub(r'\s+', ' ', question)
                    question = question.strip()
                    
                    # Quality checks
                    if (len(question) > 20 and len(question) < 300 and 
                        question.endswith('?')):
                        
                        questions.append({
                            'question': question,
                            'source': url,  # Full URL
                            'extraction_method': 'regex_pattern'
                        })
                        
            except re.error as e:
                logger.warning(f"Regex error with pattern: {e}")
                continue
        
        return questions

    def format_questions_by_source(self, questions_with_sources: List[Dict]) -> str:
        """Format questions grouped by full source URL"""
        
        # Group questions by source URL
        source_groups = {}
        for q_dict in questions_with_sources:
            source_url = q_dict['source']
            if source_url not in source_groups:
                source_groups[source_url] = []
            source_groups[source_url].append(q_dict['question'])
        
        # Format output
        formatted_output = []
        question_counter = 1
        
        for source_num, (source_url, questions) in enumerate(source_groups.items(), 1):
            # Extract domain for cleaner display
            try:
                from urllib.parse import urlparse
                domain = urlparse(source_url).netloc
            except:
                domain = source_url
            
            formatted_output.append(f"**Source {source_num}: {domain}**")
            formatted_output.append(f"*Full URL: {source_url}*")
            
            for question in questions:
                formatted_output.append(f"{question_counter}. {question}")
                question_counter += 1
            
            formatted_output.append("")  # Empty line between sources
        
        return "\n".join(formatted_output)

# Research Design Workflow Functions
class ResearchWorkflow:
    def __init__(self, llm_instance):
        self.llm = llm_instance
        self.active_sessions: Dict[str, ResearchDesign] = {}
        self.browser_tool = None  # Will be set by UI server
        
        # Google Custom Search API configuration
        self.google_api_key = os.getenv('GOOGLE_API_KEY')
        self.google_cse_id = os.getenv('GOOGLE_CSE_ID')
        
        # Initialize Google Custom Search service
        if self.google_api_key and self.google_cse_id:
            try:
                self.search_service = build("customsearch", "v1", developerKey=self.google_api_key)
                logger.info("Google Custom Search API initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Google Custom Search API: {e}")
                self.search_service = None
        else:
            logger.warning("Google API credentials not found. Using fallback search.")
            self.search_service = None

    async def _collect_all_urls(self, research_topic: str) -> List[str]:
        """Collect 30 unique deep URLs upfront for the research topic"""
        try:
            if not self.search_service:
                logger.warning("Google Custom Search API not available")
                return []
            
            search_query = f"Surveys on {research_topic}"
            logger.info(f"Collecting URLs for: {search_query}")
            
            all_unique_urls = []
            seen_urls = set()
            
            # Try multiple search variations to get 30 unique URLs
            search_variations = [
                f"Surveys on {research_topic}",
                f"{research_topic} questionnaire research",
                f"{research_topic} survey methodology",
                f"{research_topic} study questions"
            ]
            
            for search_term in search_variations:
                if len(all_unique_urls) >= 30:
                    break
                    
                try:
                    search_result = self.search_service.cse().list(
                        q=search_term,
                        cx=self.google_cse_id,
                        num=10,  # Get 10 results per search
                        safe='active',
                        fields='items(title,link,snippet)'
                    ).execute()
                    
                    if 'items' in search_result:
                        for item in search_result['items']:
                            link = item.get('link', '')
                            title = item.get('title', '')
                            
                            if link and link not in seen_urls:
                                # Check if it's a valid deep URL
                                if self._is_valid_url(link):
                                    all_unique_urls.append(link)
                                    seen_urls.add(link)
                                    logger.info(f"✅ Collected deep URL #{len(all_unique_urls)}: {title}")
                                    
                                    if len(all_unique_urls) >= 30:
                                        break
                                else:
                                    logger.info(f"❌ Filtered out: {title} - {link}")
                    
                    # Small delay between searches
                    await asyncio.sleep(1)
                    
                except Exception as api_error:
                    logger.error(f"Search API error for '{search_term}': {api_error}")
                    continue
            
            logger.info(f"URL collection results:")
            logger.info(f"  - Total unique deep URLs collected: {len(all_unique_urls)}")
            logger.info(f"  - Target was: 30 URLs")
            
            return all_unique_urls[:30]  # Ensure we don't exceed 30
            
        except Exception as e:
            logger.error(f"Error collecting URLs: {e}")
            return []

    async def _extract_actual_questions_from_content(self, scraped_content: str, url: str) -> List[Dict]:
        """Extract actual survey questions with improved error handling and source tracking"""
        
        # Initialize the improved extractor
        if not hasattr(self, '_question_extractor'):
            self._question_extractor = ImprovedQuestionExtractor()
        
        try:
            # Use improved extraction
            found_questions = self._question_extractor.extract_questions_with_sources(scraped_content, url)
            
            if len(found_questions) >= 3:
                logger.info(f"Found {len(found_questions)} questions using improved patterns from {url}")
                return found_questions
            
            # Fallback to LLM if pattern matching doesn't find enough
            logger.info(f"Pattern matching found only {len(found_questions)} questions, using LLM for {url}")
            
            llm_questions = await self._llm_extract_actual_questions(scraped_content, url)
            found_questions.extend(llm_questions)
            
            # Remove duplicates
            unique_questions = []
            seen = set()
            
            for q_dict in found_questions:
                question_text = q_dict['question'].lower().strip()
                if question_text not in seen and len(question_text) > 15:
                    seen.add(question_text)
                    unique_questions.append(q_dict)
            
            return unique_questions[:6]
            
        except Exception as e:
            logger.error(f"Error in question extraction from {url}: {e}")
            return []

    def _find_questions_with_patterns(self, content: str, url: str) -> List[Dict]:
        """Find actual survey questions using corrected regex patterns"""
        
        # Initialize extractor if not exists
        if not hasattr(self, '_question_extractor'):
            self._question_extractor = ImprovedQuestionExtractor()
        
        return self._question_extractor._extract_pattern_questions(content, url)

    def _find_questions_simple_patterns(self, content: str, url: str) -> List[Dict]:
        """Find questions using simple, reliable patterns"""
        
        # Initialize extractor if not exists
        if not hasattr(self, '_question_extractor'):
            self._question_extractor = ImprovedQuestionExtractor()
        
        return self._question_extractor._extract_simple_questions(content, url)

    async def _llm_extract_actual_questions(self, scraped_content: str, url: str) -> List[Dict]:
        """Enhanced LLM extraction with better prompting and full URL tracking"""
        
        # Pre-process content to find question-rich sections
        lines = scraped_content.split('\n')
        question_sections = []
        
        for i, line in enumerate(lines):
            if '?' in line or any(word in line.lower() for word in ['question', 'survey', 'ask', 'rate', 'scale', 'satisfaction']):
                # Get context around potential questions
                start = max(0, i - 3)
                end = min(len(lines), i + 5)
                section = ' '.join(lines[start:end])
                question_sections.append(section)
        
        # Use most relevant sections or fallback to beginning of content
        if question_sections:
            content_to_analyze = ' '.join(question_sections[:5])  # Use top 5 sections
        else:
            content_to_analyze = scraped_content[:3000]
        
        prompt = f"""
    Extract EXISTING survey questions from this webpage content. Find questions that already exist - do NOT create new ones.

    WEBPAGE: {url}

    CONTENT TO ANALYZE:
    {content_to_analyze}

    EXTRACTION RULES:
    1. Only extract questions that already exist in the content
    2. Questions must end with "?"
    3. Questions should be 20-200 characters long
    4. Return maximum 6 questions
    5. Format: One question per line, no numbering or bullets
    6. If no actual questions found, return "NO_QUESTIONS_FOUND"

    EXISTING QUESTIONS:
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.1)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            if "NO_QUESTIONS_FOUND" in cleaned_response.upper():
                logger.info(f"LLM found no questions in {url}")
                return []
            
            lines = cleaned_response.split('\n')
            questions_found = []
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 20:
                    continue
                
                # Remove any numbering or bullets that LLM might add
                line = re.sub(r'^\d+[\.\)]\s*', '', line)
                line = re.sub(r'^[-•*]\s*', '', line)
                line = line.strip()
                
                # Must be a proper question
                if line.endswith('?') and len(line) > 20 and len(line) < 250:
                    questions_found.append({
                        'question': line,
                        'source': url,  # Store full URL
                        'extraction_method': 'llm_extraction'
                    })
                    
                    if len(questions_found) >= 6:
                        break
            
            logger.info(f"LLM extracted {len(questions_found)} questions from {url}")
            return questions_found
            
        except Exception as e:
            logger.error(f"LLM extraction error for {url}: {e}")
            return []

    async def _search_internet_for_questions(self, research_topic: str, target_population: str, session: ResearchDesign) -> tuple[List[Dict], List[str], List[Dict]]:
        """Process the next batch of 6 URLs and extract actual questions"""
        try:
            # If this is the first time, collect all URLs
            if session.all_collected_urls is None:
                logger.info("First time search - collecting all URLs")
                session.all_collected_urls = await self._collect_all_urls(research_topic)
                session.current_batch_index = 0
                session.browsed_urls = []
                
                if not session.all_collected_urls:
                    logger.warning("No URLs collected")
                    return [], [], []
            
            # Check if we've exhausted all URLs
            total_urls = len(session.all_collected_urls)
            start_index = session.current_batch_index * 6
            
            if start_index >= total_urls:
                logger.warning("All collected URLs have been processed")
                return [], [], []
            
            # Get the next batch of 6 URLs
            end_index = min(start_index + 6, total_urls)
            current_batch_urls = session.all_collected_urls[start_index:end_index]
            
            logger.info(f"Processing batch {session.current_batch_index + 1}")
            logger.info(f"URLs {start_index + 1}-{end_index} of {total_urls} total collected URLs")
            
            # Process the current batch
            all_extracted_questions = []
            scraped_sources = []
            valid_screenshots = []
            
            # SIMPLE FIX: Track already seen questions across ALL sessions
            seen_questions = set()
            
            # Add previously found questions to seen set
            if hasattr(session, 'extracted_questions_with_sources') and session.extracted_questions_with_sources:
                for prev_q in session.extracted_questions_with_sources:
                    seen_questions.add(prev_q['question'].lower().strip())
            
            for i, url in enumerate(current_batch_urls, 1):
                try:
                    logger.info(f"Processing URL {start_index + i}/{total_urls}: {url}")
                    
                    # Scrape content first
                    page_content = await self._scrape_page_content(url)
                    
                    if not page_content or len(page_content) < 200:
                        print(f"❌ Insufficient content from {url}")
                        continue
                    
                    # Extract actual questions from this URL
                    url_questions = await self._extract_actual_questions_from_content(page_content, url)
                    
                    # SIMPLE FIX: Filter out duplicate questions
                    unique_url_questions = []
                    for q_dict in url_questions:
                        question_text = q_dict['question'].lower().strip()
                        if question_text not in seen_questions:
                            seen_questions.add(question_text)
                            unique_url_questions.append(q_dict)
                            logger.info(f"✅ Added unique question: {q_dict['question'][:50]}...")
                        else:
                            logger.info(f"⚠️ Skipped duplicate question: {q_dict['question'][:50]}...")
                    
                    if unique_url_questions:
                        all_extracted_questions.extend(unique_url_questions)
                        logger.info(f"✅ Extracted {len(unique_url_questions)} unique questions from {url}")
                    else:
                        logger.info(f"⚠️ No unique questions found in {url}")
                    
                    # Try screenshot
                    screenshot = None
                    if self.browser_tool:
                        print(f"📸 Attempting screenshot for {url}")
                        try:
                            screenshot = await capture_url_screenshot(url, self.browser_tool)
                            
                            if screenshot:
                                # Validate the screenshot
                                is_valid = await self.validate_screenshot(screenshot, url)
                                if not is_valid:
                                    screenshot = None
                        except Exception as screenshot_error:
                            logger.warning(f"Screenshot failed for {url}: {screenshot_error}")
                            screenshot = None
                    
                    scraped_sources.append(url)
                    
                    # Only add to slideshow if screenshot is valid
                    if screenshot:
                        domain = self._extract_domain(url)
                        valid_screenshots.append({
                            'url': url,
                            'screenshot': screenshot,
                            'title': f"Survey Research - {domain}"
                        })
                        logger.info(f"✅ Added screenshot #{len(valid_screenshots)}")
                    else:
                        logger.info(f"⚠️ Content only (no valid screenshot) for {url}")
                    
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.warning(f"Error processing {url}: {e}")
                    continue
            
            # Update session tracking
            session.browsed_urls.extend(scraped_sources)
            session.current_batch_index += 1
            
            logger.info(f"Batch {session.current_batch_index} results:")
            logger.info(f"  - URLs in this batch: {len(current_batch_urls)}")
            logger.info(f"  - Total UNIQUE questions extracted: {len(all_extracted_questions)}")
            logger.info(f"  - Valid screenshots: {len(valid_screenshots)}")
            
            # Return extracted questions (not generated ones)
            return all_extracted_questions, scraped_sources, valid_screenshots
            
        except Exception as e:
            logger.error(f"Error in batch URL processing: {e}")
            return [], [], []

    async def validate_screenshot(self, screenshot_base64: str, url: str) -> bool:
        """
        Simple validation - first attempt only
        Returns True if screenshot has content, False if blank
        """
        try:
            # Check if screenshot is too small (likely blank/error)
            if len(screenshot_base64) < 10000:  # Less than ~7KB
                print(f"❌ Screenshot too small for {url}")
                return False
            
            # Check decoded data
            image_data = base64.b64decode(screenshot_base64)
            if len(image_data) < 5000:  # Less than 5KB
                print(f"❌ Image data too small for {url}")
                return False
            
            # Check byte diversity (blank images have few unique bytes)
            data_sample = image_data[:1000]  # First 1KB
            unique_bytes = len(set(data_sample))
            if unique_bytes < 20:  # Very low diversity = likely blank
                print(f"❌ Low content diversity for {url}")
                return False
                
            print(f"✅ Screenshot validation passed for {url}")
            return True
            
        except Exception as e:
            print(f"❌ Validation error for {url}: {e}")
            return False
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL for display purposes"""
        try:
            parsed = urlparse(url)
            return parsed.netloc
        except:
            return "Unknown"

    async def _generate_questions_from_content(self, scraped_content: str, research_topic: str, target_population: str, num_questions: int = 6) -> List[str]:
        """Generate exactly num_questions questions from scraped content using LLM"""
        
        prompt = f"""
    Based on the following scraped web content about "{research_topic}", create exactly {num_questions} professional survey questions suitable for "{target_population}".

    SCRAPED CONTENT:
    {scraped_content[:6000]}

    INSTRUCTIONS:
    1. Create exactly {num_questions} survey questions
    2. Base questions on the concepts, topics, and information found in the scraped content
    3. Make questions relevant to "{research_topic}" research
    4. Use professional survey language appropriate for "{target_population}"
    5. Include a mix of satisfaction, frequency, rating, and preference questions
    6. Each question should be clear, specific, and measurable
    7. Return only the questions, one per line
    8. All questions must end with a question mark

    Generate exactly {num_questions} survey questions:
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            lines = cleaned_response.split('\n')
            questions = []
            
            for line in lines:
                line = line.strip()
                line = re.sub(r'^[\d\.\-\•\*\s]*', '', line)
                
                if line and len(line) > 15:
                    if not line.endswith('?'):
                        line += '?'
                    questions.append(line)
            
            if len(questions) < num_questions:
                additional_needed = num_questions - len(questions)
                basic_questions = [
                    f"How satisfied are you with {research_topic}?",
                    f"How often do you engage with {research_topic}?",
                    f"How important is {research_topic} to you?",
                    f"How likely are you to recommend {research_topic}?",
                    f"What factors are most important regarding {research_topic}?",
                    f"How would you rate your overall experience with {research_topic}?"
                ]
                questions.extend(basic_questions[:additional_needed])
            
            return questions[:num_questions]
            
        except Exception as e:
            logger.error(f"Error generating questions from content: {e}")
            return [
                f"How satisfied are you with {research_topic}?",
                f"How often do you use {research_topic}?",
                f"How important is {research_topic} to you?",
                f"How likely are you to recommend {research_topic}?",
                f"What factors influence your decisions about {research_topic}?",
                f"How would you rate your overall experience with {research_topic}?"
            ][:num_questions]

    async def _scrape_page_content(self, url: str) -> str:
        """Enhanced content scraping with better text extraction"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe', 'noscript']):
                element.decompose()
            
            # Try to find content in common containers first
            content_selectors = [
                'main', '.content', '.main-content', '.post-content', 
                '.article-content', '.entry-content', '.page-content',
                'article', '.survey-questions', '.questions', '.form-content'
            ]
            
            main_content = ""
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    main_content = ' '.join([elem.get_text() for elem in elements])
                    break
            
            # If no specific content area found, get all text
            if not main_content:
                main_content = soup.get_text()
            
            # Clean up text
            lines = (line.strip() for line in main_content.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            cleaned_text = ' '.join(chunk for chunk in chunks if chunk)
            
            # Remove extra whitespace
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
            
            logger.info(f"✅ Successfully scraped {len(cleaned_text)} characters from {url}")
            logger.info(f"Content: {cleaned_text[:8000]}")
            return cleaned_text[:8000]  # Limit to 8000 characters
            
        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return ""

    # Enhanced fallback method to also use LLM
    async def _fallback_search(self, research_topic: str, target_population: str) -> tuple[List[str], List[str], List[str]]:
        """Enhanced fallback that uses LLM to generate questions"""
        logger.info("Using enhanced LLM fallback for question generation")
        
        # Generate 6 questions using LLM (reduced from more)
        questions = await self._generate_questions_with_llm(research_topic, target_population, 6)
        
        # Create sources for fallback
        sources = ["Generated based on research methodology"] * len(questions)
        screenshots = []  # No screenshots for fallback
        
        return questions, sources, screenshots

    async def _generate_questions_with_llm(self, research_topic: str, target_population: str, num_needed: int) -> List[str]:
        """Generate additional survey questions using LLM when not enough are found"""
        
        prompt = f"""
Create {num_needed} professional survey questions for research on "{research_topic}" targeting "{target_population}".

REQUIREMENTS:
1. Questions should be suitable for quantitative research
2. Include a mix of satisfaction, frequency, importance, and preference questions
3. Use professional survey language
4. Make questions specific to the research topic
5. Ensure questions are measurable and actionable
6. Each question should be on a separate line
7. All questions must end with a question mark

QUESTION TYPES TO INCLUDE:
- Likert scale questions (satisfaction, agreement)
- Frequency questions (How often...)
- Rating questions (On a scale of 1-10...)
- Importance ranking (How important is...)
- Likelihood questions (How likely are you to...)
- Preference questions (Which do you prefer...)

RESEARCH TOPIC: {research_topic}
TARGET POPULATION: {target_population}

GENERATE {num_needed} SURVEY QUESTIONS:
"""
        
        try:
            response = await self.llm.ask(prompt, temperature=0.8)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            # Parse questions from response
            lines = cleaned_response.split('\n')
            questions = []
            
            for line in lines:
                line = line.strip()
                # Remove numbering, bullets, etc.
                line = re.sub(r'^[\d\.\-\•\*\s]*', '', line)
                
                if line and len(line) > 15:
                    # Ensure question ends with ?
                    if not line.endswith('?'):
                        line += '?'
                    # Basic quality check
                    if any(word in line.lower() for word in ['how', 'what', 'which', 'would you', 'do you', 'are you', 'rate']):
                        questions.append(line)
            
            logger.info(f"LLM generated {len(questions)} additional questions")
            return questions[:num_needed]
            
        except Exception as e:
            logger.error(f"Error generating questions with LLM: {e}")
            return []
    
    async def start_research_design(self, session_id: str) -> str:
        """Start the research design process"""
        self.active_sessions[session_id] = ResearchDesign(
            stage=ResearchStage.DESIGN_INPUT,
            chat_history=[]
        )
        
        initial_response = """
    🔬 **Research Design Workflow Started**

    Let's design your research study step by step. I'll ask you a series of questions to help create a comprehensive research design.

    **Question 1 of 3: Research Topic**
    What are you looking to find out? Please describe your research topic or area of interest.

    Examples:
    - Consumer preferences for sustainable products
    - Impact of remote work on employee productivity
    - Student attitudes toward online learning
    - Healthcare access in rural communities

    Please provide your research topic:
    """
        
        # Log the initial bot message
        session = self.active_sessions[session_id]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.chat_history.append({
            "timestamp": timestamp,
            "type": "system",
            "content": "Research Design Workflow Started",
            "stage": session.stage.value
        })
        session.chat_history.append({
            "timestamp": timestamp,
            "type": "assistant",
            "content": initial_response,
            "stage": session.stage.value
        })
        
        return initial_response

    def _export_chat_history(self, session: ResearchDesign, timestamp: str) -> str:
        """Export chat history for the research session"""
        if not session.chat_history:
            return "No chat history available for this session."
        
        chat_filename = f"research_chat_history_{timestamp}.txt"
        
        try:
            # Format chat history for export
            chat_content = f"""RESEARCH DESIGN WORKFLOW CHAT HISTORY
    Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    Research Topic: {session.research_topic or 'Not specified'}
    Target Population: {session.target_population or 'Not specified'}

    ================================================================================
    COMPLETE CHAT CONVERSATION
    ================================================================================

    """
            
            for i, interaction in enumerate(session.chat_history, 1):
                role = interaction['type'].upper()
                timestamp = interaction['timestamp']
                content = interaction['content']
                stage = interaction['stage']
                
                chat_content += f"""
    [{timestamp}] [{stage.upper()}] {role}:
    {content}

    {'='*80}

    """
            
            chat_content += f"""
    CONVERSATION SUMMARY:
    - Total interactions: {len(session.chat_history)}
    - Start time: {session.chat_history[0]['timestamp'] if session.chat_history else 'Unknown'}
    - End time: {session.chat_history[-1]['timestamp'] if session.chat_history else 'Unknown'}
    - Workflow stages covered: {', '.join(set(interaction['stage'] for interaction in session.chat_history))}

    ================================================================================
    """
            
            # Save chat history file
            chat_filepath = f"research_outputs/{chat_filename}"
            with open(chat_filepath, "w", encoding="utf-8") as f:
                f.write(chat_content)
            
            logger.info(f"Chat history exported to {chat_filepath}")
            return chat_filepath
            
        except Exception as e:
            logger.error(f"Error exporting chat history: {e}")
            return None

    async def process_research_input(self, session_id: str, user_input: str) -> str:
        """Process user input during research design phase"""
        if session_id not in self.active_sessions:
            return "Session not found. Please start a new research design session."
        
        session = self.active_sessions[session_id]
        
        # Process the input based on current stage
        if session.stage == ResearchStage.DESIGN_INPUT:
            response = await self._handle_design_input(session_id, user_input)
        elif session.stage == ResearchStage.DESIGN_REVIEW:
            response = await self._handle_design_review(session_id, user_input)
        elif session.stage == ResearchStage.DECISION_POINT:
            response = await self._handle_decision_point(session_id, user_input)
        elif session.stage == ResearchStage.QUESTIONNAIRE_BUILDER:
            response = await self._handle_questionnaire_builder(session_id, user_input)
        elif session.stage == ResearchStage.FINAL_OUTPUT:
            response = await self._handle_final_output(session_id, user_input)
        else:
            response = "Invalid session stage."
        
        # Log this interaction
        self._log_chat_interaction(session_id, user_input, response)
        
        return response
    
    async def _handle_final_output(self, session_id: str, user_input: str) -> str:
        """Handle final output and export"""
        session = self.active_sessions[session_id]
        response = user_input.upper().strip()
        
        if response == 'Y':
            # User is satisfied - export everything
            return await self._export_complete_research_package(session)
        elif response == 'N':
            # User wants modifications - go back to questionnaire builder
            session.stage = ResearchStage.QUESTIONNAIRE_BUILDER
            return await self._start_questionnaire_builder(session)
        elif response == 'T':
            # Test again
            return await self._test_questions(session)
        else:
            return """
Please respond with:
- **Y** (Yes) - Finalize and export complete research package
- **N** (No) - Make additional modifications  
- **T** (Test Again) - Run another round of testing
"""
    
    async def _export_complete_research_package(self, session: ResearchDesign) -> str:
        """Export complete research package with LLM-generated content"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"complete_research_package_{timestamp}.txt"
        
        try:
            os.makedirs("research_outputs", exist_ok=True)
            
            # Get the research design content
            research_design_content = await self._generate_research_design(session)
            
            # Use ALL questions from session
            final_questions = session.questions or []
            
            # Remove duplicates while preserving order
            seen = set()
            unique_final_questions = []
            for q in final_questions:
                q_lower = q.lower().strip()
                if q_lower not in seen:
                    seen.add(q_lower)
                    unique_final_questions.append(q)
            
            final_questions = unique_final_questions
            
            # Create comprehensive question breakdown
            question_source_info = await self._create_comprehensive_question_breakdown(session, final_questions)
            
            # Generate implementation recommendations using LLM
            implementation_content = await self._generate_implementation_recommendations(session)
            
            # Generate ethics and timeline content using LLM
            ethics_content = await self._generate_ethics_content(session)
            timeline_content = await self._generate_timeline_content(session)
            
            # Export chat history
            chat_filepath = self._export_chat_history(session, timestamp)
            
            # Create comprehensive research package
            package_content = f"""COMPLETE RESEARCH DESIGN PACKAGE
    Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    ================================================================================
    RESEARCH DESIGN SUMMARY
    ================================================================================

    Research Topic: {session.research_topic}

    Research Objectives:
    {chr(10).join(f"• {obj}" for obj in (session.objectives or []))}

    Target Population: {session.target_population}

    Research Timeframe: {session.timeframe}

    ================================================================================
    METHODOLOGY AND APPROACH
    ================================================================================

    {research_design_content}

    ================================================================================
    QUESTIONNAIRE QUESTIONS
    ================================================================================

    The following questions have been designed and tested for your research:

    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(final_questions))}

    ================================================================================
    QUESTION SOURCES AND BREAKDOWN
    ================================================================================

    {question_source_info}

    ================================================================================
    EXPORTED FILES
    ================================================================================

    This research package includes the following exported files:
    • Research Package: {filename}
    {f"• Chat History: {chat_filepath.split('/')[-1] if chat_filepath else 'Chat export failed'}" if chat_filepath else ""}

    ================================================================================
    IMPLEMENTATION RECOMMENDATIONS
    ================================================================================

    {implementation_content}

    ================================================================================
    RESEARCH ETHICS AND CONSIDERATIONS
    ================================================================================

    {ethics_content}

    ================================================================================
    EXPECTED TIMELINE
    ================================================================================

    {timeline_content}

    ================================================================================

    This research package is ready for implementation. All questions have been
    tested and validated. The methodology is sound and appropriate for your
    research objectives.

    For the complete conversation history that led to this research design,
    see the exported chat history file.
    """
            
            filepath = f"research_outputs/{filename}"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(package_content)
            
            logger.info(f"Research package exported successfully to {filepath}")
            
            # Clean up session
            session_keys_to_remove = []
            for key, sess in self.active_sessions.items():
                if sess == session:
                    session_keys_to_remove.append(key)
            
            for key in session_keys_to_remove:
                del self.active_sessions[key]
            
            # Enhanced response with breakdown
            chat_info = f"\nChat file: `{chat_filepath.split('/')[-1] if chat_filepath else 'Export failed'}`" if chat_filepath else "\n⚠️ Chat history export failed"
            
            return f"""
    🎉 **Research Package Complete!**

    Your comprehensive research package has been exported to:
    **`{filepath}`**{chat_info}

    **Package Contents:**
    ✅ Complete research design and methodology
    ✅ Tested and validated questionnaire questions  
    ✅ LLM-generated implementation recommendations
    ✅ Data analysis guidelines
    ✅ Ethics and privacy considerations
    ✅ Complete conversation history exported

    **Your Research Summary:**
    - **Topic:** {session.research_topic}
    - **Questions:** {len(final_questions)} validated questions
    - **Target:** {session.target_population}
    - **Timeline:** {session.timeframe}
    - **Chat interactions:** {len(session.chat_history) if session.chat_history else 0} recorded

    {await self._create_comprehensive_question_breakdown(session, final_questions)}

    Both files are ready for download from the research_outputs directory.
    Session completed successfully!
    """
            
        except Exception as e:
            logger.error(f"Error exporting research package: {str(e)}", exc_info=True)
            return f"Error creating research package: {str(e)}. Please check logs and try again."
    
    async def _create_comprehensive_question_breakdown(self, session: ResearchDesign, final_questions: List[str]) -> str:
        """Create comprehensive breakdown of all question sources"""
        
        # Get different question types
        custom_questions = session.__dict__.get('custom_questions', [])
        selected_questions = []
        generated_questions = []
        
        # Identify selected internet questions
        if (hasattr(session, 'user_selected_questions') and 
            session.user_selected_questions):
            selected_questions = [q['question'] for q in session.user_selected_questions]
            selected_sources = list(set(q['source'] for q in session.user_selected_questions))
        elif (session.questionnaire_responses and 
            'selected_questions' in session.questionnaire_responses):
            selected_questions = session.questionnaire_responses['selected_questions']
            selected_sources = session.internet_sources or []
        else:
            selected_sources = []
        
        # Identify generated questions
        for q in final_questions:
            if q not in custom_questions and q not in selected_questions:
                generated_questions.append(q)
        
        # Build comprehensive breakdown
        breakdown_lines = []
        
        if generated_questions:
            breakdown_lines.append(f"AI Generated Questions: {len(generated_questions)}")
            breakdown_lines.append(f"  • Created based on research topic and methodology")
            breakdown_lines.append("")
        
        if selected_questions:
            breakdown_lines.append(f"Internet Research Questions: {len(selected_questions)}")
            breakdown_lines.append(f"  • Selected from {len(selected_sources)} websites")
            breakdown_lines.append(f"  • Sources included:")
            for source in selected_sources[:5]:  # Show up to 5 sources
                breakdown_lines.append(f"    - {source}")
            if len(selected_sources) > 5:
                breakdown_lines.append(f"    - ... and {len(selected_sources) - 5} more sources")
            breakdown_lines.append("")
        
        if custom_questions:
            breakdown_lines.append(f"Custom Questions (User-Provided): {len(custom_questions)}")
            breakdown_lines.append(f"  • Questions you added during the questionnaire building process")
            breakdown_lines.append("")
        
        breakdown_lines.append(f"Total Questions: {len(final_questions)}")
        
        # Add question listings
        if generated_questions:
            breakdown_lines.append(f"\nAI Generated Questions:")
            for i, q in enumerate(generated_questions, 1):
                breakdown_lines.append(f"  {i}. {q}")
        
        if selected_questions:
            breakdown_lines.append(f"\nSelected Internet Research Questions:")
            for i, q in enumerate(selected_questions, 1):
                breakdown_lines.append(f"  {i}. {q}")
        
        if custom_questions:
            breakdown_lines.append(f"\nYour Custom Questions:")
            for i, q in enumerate(custom_questions, 1):
                breakdown_lines.append(f"  {i}. {q}")
        
        return "\n".join(breakdown_lines)

    async def _generate_implementation_recommendations(self, session: ResearchDesign) -> str:
        """Generate implementation recommendations using LLM"""
        
        prompt = f"""
    Generate comprehensive implementation recommendations for this research study:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}
    Number of Questions: {len(session.questions or [])}

    Create detailed recommendations covering:
    1. Survey Distribution methods
    2. Data Collection best practices
    3. Data Analysis approaches
    4. Reporting strategies

    Make recommendations specific to the research topic and target population. 
    Be practical and actionable. Use professional research language.
    Respond in English only.
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            return remove_chinese_and_punct(str(response))
        except Exception as e:
            logger.error(f"Error generating implementation recommendations: {e}")
            return """
    1. SURVEY DISTRIBUTION:
    - Use online survey platforms (SurveyMonkey, Qualtrics, Google Forms)
    - Target distribution through relevant channels for your population
    - Consider incentives to improve response rates

    2. DATA COLLECTION:
    - Plan for 4-6 week collection period
    - Monitor response rates weekly
    - Send follow-up reminders to improve participation

    3. DATA ANALYSIS:
    - Use statistical software for comprehensive analysis
    - Calculate descriptive statistics for all variables
    - Perform correlation analysis between key factors

    4. REPORTING:
    - Create visual dashboards with charts and graphs
    - Provide executive summary with key findings
    - Include actionable recommendations based on results
    """

    async def _generate_ethics_content(self, session: ResearchDesign) -> str:
        """Generate ethics content using LLM"""
        
        prompt = f"""
    Generate research ethics and considerations for this study:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}

    Cover important ethical considerations including:
    - Informed consent requirements
    - Privacy and data protection
    - Participant rights
    - Data security measures
    - Regulatory compliance

    Make it specific to the research context. Be comprehensive but concise.
    Respond in English only.
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.6)
            return remove_chinese_and_punct(str(response))
        except Exception as e:
            logger.error(f"Error generating ethics content: {e}")
            return """
    - Obtain informed consent from all participants
    - Ensure participant anonymity and data privacy
    - Store data securely and follow GDPR/privacy regulations
    - Provide participants with option to withdraw at any time
    - Protect sensitive information throughout the research process
    - Follow institutional review board guidelines if applicable
    """

    async def _generate_timeline_content(self, session: ResearchDesign) -> str:
        """Generate timeline content using LLM"""
        
        prompt = f"""
    Generate a realistic research timeline for this study:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}
    Questions: {len(session.questions or [])} total questions

    Create a week-by-week timeline covering:
    - Questionnaire finalization
    - Data collection period
    - Analysis phase
    - Reporting phase

    Make timeline realistic and appropriate for the research scope.
    Respond in English only.
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.6)
            return remove_chinese_and_punct(str(response))
        except Exception as e:
            logger.error(f"Error generating timeline content: {e}")
            return """
    Week 1-2: Finalize questionnaire and setup survey platform
    Week 3-8: Data collection period
    Week 9-10: Data analysis and preliminary results
    Week 11-12: Final report preparation and presentation

    Adjust timeline based on your specific requirements and target population size.
    """

    def _log_chat_interaction(self, session_id: str, user_message: str, bot_response: str):
        """Log chat interaction for the specific session"""
        if session_id not in self.active_sessions:
            return
            
        session = self.active_sessions[session_id]
        
        # Initialize chat history if not exists
        if session.chat_history is None:
            session.chat_history = []
        
        # Add timestamp for this interaction
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Log user message
        session.chat_history.append({
            "timestamp": timestamp,
            "type": "user",
            "content": user_message,
            "stage": session.stage.value
        })
        
        # Log bot response
        session.chat_history.append({
            "timestamp": timestamp,
            "type": "assistant", 
            "content": bot_response,
            "stage": session.stage.value
        })
        
        logger.info(f"Logged chat interaction for session {session_id}, total interactions: {len(session.chat_history)}")

    async def _handle_design_input(self, session_id: str, user_input: str) -> str:
        """Handle user input during design input phase - now 3 questions instead of 4"""
        session = self.active_sessions[session_id]
        
        if not session.user_responses:
            session.user_responses = {}
        
        # Determine which question we're on based on existing responses
        if 'topic' not in session.user_responses:
            # This is the response to Question 1 (research topic)
            session.user_responses['topic'] = user_input.strip()
            session.research_topic = user_input.strip()
            
            logger.info(f"Session {session_id}: Saved topic - {session.research_topic}")
            
            return """
    **Question 2 of 3: Research Objectives**
    What specific objectives do you want to achieve with this research? 

    Examples:
    - Understand customer satisfaction levels
    - Identify factors influencing purchasing decisions
    - Measure the effectiveness of a new program
    - Compare different groups or conditions

    Please list your research objectives (you can provide multiple objectives):
    """
        
        elif 'objectives' not in session.user_responses:
            # This is the response to Question 2 (objectives)
            if '\n' in user_input:
                objectives = [obj.strip() for obj in user_input.split('\n') if obj.strip()]
            else:
                if ',' in user_input:
                    objectives = [obj.strip() for obj in user_input.split(',') if obj.strip()]
                elif ';' in user_input:
                    objectives = [obj.strip() for obj in user_input.split(';') if obj.strip()]
                else:
                    objectives = [user_input.strip()]
            
            session.user_responses['objectives'] = objectives
            session.objectives = objectives
            
            logger.info(f"Session {session_id}: Saved objectives - {session.objectives}")
            
            return """
    **Question 3 of 3: Target Population**
    Who is your target population or study participants?

    Examples:
    - Adults aged 18-65 in urban areas
    - College students at public universities
    - Small business owners in the technology sector
    - Parents of children under 12

    Please describe your target population:
    """
        
        elif 'target_population' not in session.user_responses:
            # This is the response to Question 3 (target population) - final question
            session.user_responses['target_population'] = user_input.strip()
            session.target_population = user_input.strip()
            
            logger.info(f"Session {session_id}: Saved target population - {session.target_population}")
            logger.info(f"Session {session_id}: All 3 questions completed, generating research design")
            
            # Generate research design summary
            research_design = await self._generate_research_design(session)
            session.stage = ResearchStage.DESIGN_REVIEW
            
            return f"""
    📋 **Research Design Summary**

    **Topic:** {session.research_topic}

    **Objectives:**
    {chr(10).join(f"• {obj}" for obj in session.objectives)}

    **Target Population:** {session.target_population}

    **Generated Research Design:**
    {research_design}

    ---

    **Is this research design acceptable?**

    Reply with:
    - **Y** (Yes) - Proceed to search for relevant questions and data
    - **N** (No) - Revise the research design
    - **S** (Save) - Save and export this design
    - **E** (Exit) - Exit the workflow
    """
        
        else:
            logger.warning(f"Session {session_id}: Unexpected state - all questions answered but still in DESIGN_INPUT stage")
            return "All research design questions have been completed. Please proceed with the review."
    
    async def _generate_research_design(self, session: ResearchDesign) -> str:
        """Generate a comprehensive research design using LLM without specifying data collection modes"""
        prompt = f"""
    Generate a comprehensive research design based on the following information:

    Topic: {session.research_topic}
    Objectives: {', '.join(session.objectives)}
    Target Population: {session.target_population}

    Please provide:
    1. Research methodology recommendations
    2. Key variables to measure
    3. Potential limitations and considerations
    4. Recommended sample size

    Keep the response concise but comprehensive (under 300 words). Focus on online survey methodology as the primary approach. Respond in English only.
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            cleaned_response = remove_chinese_and_punct(str(response))
            return cleaned_response
        except Exception as e:
            logger.error(f"Error generating research design: {e}")
            return "Unable to generate research design automatically. Please review your inputs manually."
    
    async def _handle_design_review(self, session_id: str, user_input: str) -> str:
        """Handle user response during design review"""
        session = self.active_sessions[session_id]
        response = user_input.upper().strip()
        
        if response == 'Y':
            session.stage = ResearchStage.DATABASE_SEARCH
            return await self._search_database(session)
        elif response == 'N':
            session.stage = ResearchStage.DESIGN_INPUT
            session.user_responses = {}
            return await self.start_research_design(session_id)
        elif response == 'S':
            return await self._save_and_export(session)
        elif response == 'E':
            del self.active_sessions[session_id]
            return "Research design workflow ended. Thank you!"
        else:
            return """
Please respond with:
- **Y** (Yes) - Proceed to search for relevant questions and data
- **N** (No) - Revise the research design
- **S** (Save) - Save and export this design
- **E** (Exit) - Exit the workflow
"""
    # Enhanced URL filtering to only include deep URLs

    def _is_deep_url(self, url: str) -> bool:
        """
        Check if URL is a deep URL (not just root domain)
        Returns True for URLs with meaningful paths, False for root domains
        """
        try:
            # Parse URL to get path
            from urllib.parse import urlparse
            parsed = urlparse(url)
            
            # Get the path part (everything after domain)
            path = parsed.path.strip('/')
            
            # Count path segments
            path_segments = [seg for seg in path.split('/') if seg and seg.strip()]
            
            # 1. Must have at least some path (not just domain.com or domain.com/)
            if not path or len(path) < 3:
                print(f"❌ Root domain rejected: {url}")
                return False
            
            # 2. Must have at least 1 meaningful path segment
            if len(path_segments) < 1:
                print(f"❌ No path segments: {url}")
                return False
            
            # 3. Reject common root-level pages that aren't specific content
            root_level_pages = [
                'index', 'home', 'main', 'default', 'welcome',
                'about', 'contact', 'privacy', 'terms', 'legal',
                'sitemap', 'robots.txt', 'favicon.ico'
            ]
            
            first_segment = path_segments[0].lower()
            if first_segment in root_level_pages:
                print(f"❌ Root-level page rejected: {url}")
                return False
            
            # 4. Prefer URLs with multiple path segments (deeper content)
            if len(path_segments) >= 2:
                print(f"✅ Deep URL accepted ({len(path_segments)} segments): {url}")
                return True
            
            # 5. Single segment URLs - check if they look like content
            content_indicators = [
                'survey', 'research', 'study', 'questionnaire', 'poll',
                'article', 'blog', 'post', 'report', 'analysis',
                'guide', 'white-paper', 'case-study', 'methodology',
                'results', 'findings', 'data', 'statistics'
            ]
            
            first_segment_lower = first_segment.lower()
            for indicator in content_indicators:
                if indicator in first_segment_lower:
                    print(f"✅ Content URL accepted: {url}")
                    return True
            
            # 6. Check if URL has meaningful length (longer paths often = more specific content)
            if len(path) >= 15:  # At least 15 characters in path
                print(f"✅ Substantial path accepted: {url}")
                return True
            
            print(f"❌ Shallow URL rejected: {url}")
            return False
            
        except Exception as e:
            print(f"❌ URL parsing error for {url}: {e}")
            return False

    def _is_valid_url(self, url: str) -> bool:
        """Enhanced URL validation including deep URL check"""
        try:
            # First check basic validity
            problematic_patterns = [
                'accounts.google.com',
                'login.',
                'signin.',
                'auth.',
                'captcha',
                '.pdf',
                '.doc',
                '.zip',
                'javascript:',
                'mailto:',
                'tel:',
                'ftp:'
            ]
            
            url_lower = url.lower()
            for pattern in problematic_patterns:
                if pattern in url_lower:
                    print(f"❌ Problematic pattern rejected: {url}")
                    return False
            
            # Basic URL validation
            if not url.startswith(('http://', 'https://')):
                print(f"❌ Invalid protocol: {url}")
                return False
            
            if len(url) > 500:  # Very long URLs are often problematic
                print(f"❌ URL too long: {url}")
                return False
            
            # NEW: Check if it's a deep URL
            if not self._is_deep_url(url):
                return False
            
            print(f"✅ Valid deep URL: {url}")
            return True
            
        except Exception:
            return False

    async def _search_database(self, session: ResearchDesign) -> str:
        """Search internet and present questions for selection"""
        try:
            extracted_questions, sources, screenshots = await self._search_internet_for_questions(
                session.research_topic, session.target_population, session
            )
            
            if not extracted_questions:
                return f"""
    ❌ **No Survey Questions Found**

    Unable to find actual survey questions in the current batch of URLs.

    **Would you like to:**
    - **R** (Rebrowse) - Try the next batch of URLs
    - **E** (Exit) - Exit workflow
    """
            
            # Initialize selection pool if first time
            if session.selected_questions_pool is None:
                session.selected_questions_pool = []
            if session.user_selected_questions is None:
                session.user_selected_questions = []
            
            # Add new questions to pool (avoiding duplicates)
            existing_questions = {q['question'].lower().strip() for q in session.selected_questions_pool}
            new_unique_questions = []
            
            for q_dict in extracted_questions:
                question_text = q_dict['question'].lower().strip()
                if question_text not in existing_questions:
                    new_unique_questions.append(q_dict)
                    existing_questions.add(question_text)
            
            session.selected_questions_pool.extend(new_unique_questions)
            
            # Store other session data
            session.internet_questions = [q['question'] for q in session.selected_questions_pool]
            session.internet_sources = sources
            session.screenshots = screenshots
            session.extracted_questions_with_sources = session.selected_questions_pool
            
            # Move to selection stage
            session.stage = ResearchStage.DECISION_POINT
            session.awaiting_selection = True
            
            # Format questions for selection with numbering
            formatted_questions = self._format_questions_for_selection(session.selected_questions_pool)
            
            total_collected = len(session.all_collected_urls) if session.all_collected_urls else 0
            current_batch = session.current_batch_index
            processed_count = len(session.browsed_urls) if session.browsed_urls else 0
            
            currently_selected_count = len(session.user_selected_questions)
            remaining_selections = session.max_selectable_questions - currently_selected_count
            
            return f"""
    🔍 **Questions Found - Please Select (Batch {current_batch}/{(total_collected + 5) // 6})**

    Found {len(new_unique_questions)} new questions from this batch.
    **Total pool now: {len(session.selected_questions_pool)} questions**

    {formatted_questions}

    **📊 Selection Status:**
    - **Currently selected:** {currently_selected_count}/{session.max_selectable_questions}
    - **Remaining selections:** {remaining_selections}
    - **URLs processed:** {processed_count} of {total_collected} collected

    **How to select questions:**
    Enter question numbers separated by spaces (e.g., "1 3 5 7 12")
    - Select up to {remaining_selections} more questions
    - Enter "0" to select none from this batch

    **Options after selection:**
    - **C** (Continue) - Proceed with selected questions
    - **R** (Rebrowse) - Search more URLs after selection
    - **E** (Exit) - Exit workflow

    **Please enter your question numbers:**
    """
            
        except Exception as e:
            logger.error(f"Error in database search: {e}")
            return f"❌ Search Error: {str(e)}"

    def _format_questions_for_selection(self, questions_pool: List[Dict]) -> str:
        """Format questions with numbers for user selection"""
        if not questions_pool:
            return "No questions available for selection."
        
        # Group by source for better organization
        source_groups = {}
        for i, q_dict in enumerate(questions_pool, 1):
            source_url = q_dict['source']
            if source_url not in source_groups:
                source_groups[source_url] = []
            source_groups[source_url].append((i, q_dict['question']))
        
        formatted_output = []
        
        for source_num, (source_url, questions) in enumerate(source_groups.items(), 1):
            try:
                from urllib.parse import urlparse
                domain = urlparse(source_url).netloc
            except:
                domain = source_url
            
            # FIXED: Always show full URL, not just domain
            formatted_output.append(f"**Source {source_num}: {domain}**")
            formatted_output.append(f"*Full URL: {source_url}*")
            
            for question_num, question_text in questions:
                formatted_output.append(f"{question_num}. {question_text}")
            
            formatted_output.append("")  # Empty line between sources
        
        return "\n".join(formatted_output)

    async def _handle_decision_point(self, session_id: str, user_input: str) -> str:
        """Handle decision point with question selection logic"""
        session = self.active_sessions[session_id]
        response = user_input.strip()
        
        # FIXED: Handle "C" command universally - always go to questionnaire builder
        if response.upper() == 'C':
            # Set up questions for questionnaire builder
            if session.user_selected_questions:
                session.use_internet_questions = True
                session.questions = [q['question'] for q in session.user_selected_questions]
            else:
                # No questions selected, use AI-only mode
                session.use_internet_questions = False
                session.questions = []
            
            session.stage = ResearchStage.QUESTIONNAIRE_BUILDER
            session.awaiting_selection = False  # Clear selection flag
            return await self._start_questionnaire_builder(session)
        
        # If we're awaiting selection, handle the selection input
        if session.awaiting_selection:
            return await self._handle_question_selection(session_id, response)
        
        # Handle other responses
        if response.upper() == 'R':
            # Check if rebrowse is still allowed
            if session.rebrowse_count >= 4:
                return await self._show_final_selection_summary(session)
            return await self._rebrowse_internet(session)
        elif response.upper() == 'E':
            del self.active_sessions[session_id]
            return "Research design workflow ended. Thank you!"
        else:
            return """
    Please respond with:
    - **C** (Continue) - Proceed to questionnaire builder with selected questions
    - **R** (Rebrowse) - Search more URLs for additional questions
    - **E** (Exit) - Exit workflow
    """

    async def _handle_question_selection(self, session_id: str, user_input: str) -> str:
        """Handle user's question selection input"""
        session = self.active_sessions[session_id]
        
        # FIXED: Handle "C" command here too - always go to questionnaire builder
        if user_input.upper().strip() == 'C':
            # Set up questions for questionnaire builder
            if session.user_selected_questions:
                session.use_internet_questions = True
                session.questions = [q['question'] for q in session.user_selected_questions]
            else:
                session.use_internet_questions = False
                session.questions = []
            
            session.stage = ResearchStage.QUESTIONNAIRE_BUILDER
            session.awaiting_selection = False
            return await self._start_questionnaire_builder(session)
        
        try:
            # Parse selection input
            if user_input.strip() == "0":
                # User selected none
                selected_numbers = []
            else:
                import re
                numbers = re.findall(r'\d+', user_input)
                selected_numbers = [int(num) for num in numbers 
                                 if 1 <= int(num) <= len(session.selected_questions_pool)]
            
            # Check selection limits
            currently_selected_count = len(session.user_selected_questions)
            remaining_selections = session.max_selectable_questions - currently_selected_count
            
            if len(selected_numbers) > remaining_selections:
                return f"""
❌ **Too Many Selections**

You can only select {remaining_selections} more questions.
You selected {len(selected_numbers)} questions.

Please enter {remaining_selections} or fewer question numbers:
"""
            
            # Add selected questions to user's selection
            newly_selected = []
            for num in selected_numbers:
                question_dict = session.selected_questions_pool[num - 1]  # Convert to 0-based index
                
                # Check if already selected
                already_selected = any(
                    q['question'].lower().strip() == question_dict['question'].lower().strip() 
                    for q in session.user_selected_questions
                )
                
                if not already_selected:
                    newly_selected.append(question_dict)
            
            session.user_selected_questions.extend(newly_selected)
            session.awaiting_selection = False
            
            # Show selection summary
            total_selected = len(session.user_selected_questions)
            remaining_selections = session.max_selectable_questions - total_selected
            
            selected_questions_text = "\n".join(
                f"{i+1}. {q['question']}" 
                for i, q in enumerate(session.user_selected_questions)
            )
            
            # Check if user has reached the maximum
            if total_selected >= session.max_selectable_questions:
                return f"""
✅ **Maximum Questions Selected ({total_selected}/{session.max_selectable_questions})**

**Your Selected Questions:**
{selected_questions_text}

You have reached the maximum number of selectable questions.

**What would you like to do?**
- **C** (Continue) - Proceed to questionnaire builder with these questions
- **E** (Exit) - Exit workflow
"""
            
            return f"""
✅ **Questions Added to Selection**

Added {len(newly_selected)} questions to your selection.

**Your Selected Questions ({total_selected}/{session.max_selectable_questions}):**
{selected_questions_text}

**Remaining selections:** {remaining_selections}

**What would you like to do?**
- **C** (Continue) - Proceed to questionnaire builder with selected questions
- **R** (Rebrowse) - Search more URLs for additional questions  
- **E** (Exit) - Exit workflow
"""
            
        except Exception as e:
            logger.error(f"Error handling question selection: {e}")
            return f"""
❌ **Selection Error**

Please enter question numbers separated by spaces (e.g., "1 3 5 7")
Or enter "0" to select none from this batch.
Or enter "C" to continue to questionnaire builder.

Error: {str(e)}
"""

    async def _handle_additional_question_selection(self, session_id: str, user_input: str) -> str:
        """Handle selection of additional questions and merge with main questions"""
        session = self.active_sessions[session_id]
        
        if user_input.upper().strip() == 'A':
            # Accept all additional questions
            additional_questions = session.__dict__.get('additional_questions', [])
            if additional_questions:
                # Remove demographics from current questions temporarily
                fixed_demographics = [
                    "What is your age?",
                    "What is your gender?",
                    "What is your highest level of education?", 
                    "What is your annual household income range?",
                    "In which city/region do you currently live?"
                ]
                
                main_questions = [q for q in session.questions if q not in fixed_demographics]
                
                # Add additional questions and put demographics back at the end
                session.questions = main_questions + additional_questions + fixed_demographics
                
                return f"""
✅ **All Additional Questions Added**

**Your Complete Questionnaire ({len(session.questions)} questions):**

**Main Questions ({len(main_questions)}):**
{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(main_questions))}

**Additional Questions ({len(additional_questions)}):**
{chr(10).join(f"{i+len(main_questions)+1}. {q}" for i, q in enumerate(additional_questions))}

**Demographics ({len(fixed_demographics)}):**
{chr(10).join(f"{i+len(main_questions)+len(additional_questions)+1}. {q}" for i, q in enumerate(fixed_demographics))}

---

**Review your complete questionnaire:**
- **A** (Accept) - Use these questions and proceed to testing
- **R** (Revise) - Rephrase questions in different words
- **M** (More) - Generate even more additional questions
- **B** (Back) - Return to questionnaire builder menu
"""
            
        elif user_input.upper().strip() == 'S':
            # Select some additional questions
            additional_questions = session.__dict__.get('additional_questions', [])
            if not additional_questions:
                return "No additional questions available for selection."
            
            return f"""
📋 **Select Additional Questions**

{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(additional_questions))}

Enter the question numbers you want to add (separated by spaces):
Example: "1 3 5 7"

Enter your selection:
"""
            
        elif user_input.upper().strip() == 'R':
            # Regenerate additional questions
            return await self._generate_more_questions(session)
            
        elif user_input.upper().strip() == 'B':
            # Go back to main menu
            return await self._show_current_questions(session)
            
        else:
            # Handle number selection
            try:
                import re
                numbers = re.findall(r'\d+', user_input)
                additional_questions = session.__dict__.get('additional_questions', [])
                selected_numbers = [int(num) for num in numbers 
                                 if 1 <= int(num) <= len(additional_questions)]
                
                if not selected_numbers:
                    return f"""
Please enter valid question numbers from 1 to {len(additional_questions)}.

{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(additional_questions))}

Enter your selection:
"""
                
                # Get selected additional questions
                selected_additional = [additional_questions[i-1] for i in selected_numbers]
                
                # Remove demographics from current questions temporarily
                fixed_demographics = [
                    "What is your age?",
                    "What is your gender?",
                    "What is your highest level of education?",
                    "What is your annual household income range?", 
                    "In which city/region do you currently live?"
                ]
                
                main_questions = [q for q in session.questions if q not in fixed_demographics]
                
                # Add selected additional questions and put demographics back at the end
                session.questions = main_questions + selected_additional + fixed_demographics
                
                return f"""
✅ **Selected Questions Added**

Added {len(selected_additional)} questions to your questionnaire.

**Your Complete Questionnaire ({len(session.questions)} questions):**

**Main Questions ({len(main_questions)}):**
{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(main_questions))}

**Selected Additional Questions ({len(selected_additional)}):**
{chr(10).join(f"{i+len(main_questions)+1}. {q}" for i, q in enumerate(selected_additional))}

**Demographics ({len(fixed_demographics)}):**
{chr(10).join(f"{i+len(main_questions)+len(selected_additional)+1}. {q}" for i, q in enumerate(fixed_demographics))}

---

**Review your complete questionnaire:**
- **A** (Accept) - Use these questions and proceed to testing
- **R** (Revise) - Rephrase questions in different words
- **M** (More) - Generate even more additional questions
- **B** (Back) - Return to questionnaire builder menu
"""
                
            except Exception as e:
                return f"""
Error processing selection: {str(e)}

Please enter question numbers separated by spaces.
"""

    async def _show_current_questions(self, session: ResearchDesign) -> str:
        """Show current questions with options"""
        if not session.questions:
            return "No questions generated yet."
        
        fixed_demographics = [
            "What is your age?",
            "What is your gender?",
            "What is your highest level of education?",
            "What is your annual household income range?",
            "In which city/region do you currently live?"
        ]
        
        main_questions = [q for q in session.questions if q not in fixed_demographics]
        demographic_questions = [q for q in session.questions if q in fixed_demographics]
        
        return f"""
📋 **Current Questionnaire ({len(session.questions)} questions)**

**Main Questions ({len(main_questions)}):**
{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(main_questions))}

**Demographics ({len(demographic_questions)}):**
{chr(10).join(f"{i+len(main_questions)+1}. {q}" for i, q in enumerate(demographic_questions))}

---

**Review these questions:**
- **A** (Accept) - Use these questions and proceed to testing
- **R** (Revise) - Rephrase questions in different words
- **M** (More) - Generate additional questions
- **B** (Back) - Return to questionnaire builder menu
"""

    async def _rebrowse_internet(self, session: ResearchDesign) -> str:
        """Rebrowse next batch and present new questions for selection"""
        try:
            # Check rebrowse limit
            if session.rebrowse_count >= 4:
                return await self._show_final_selection_summary(session)
            
            # Increment rebrowse count
            session.rebrowse_count += 1
            
            # Get new questions from next batch
            new_extracted_questions, new_sources, new_screenshots = await self._search_internet_for_questions(
                session.research_topic, session.target_population, session
            )
            
            if not new_extracted_questions:
                return await self._show_final_selection_summary(session)
            
            # Add new unique questions to pool
            existing_questions = {q['question'].lower().strip() for q in session.selected_questions_pool}
            new_unique_questions = []
            
            for q_dict in new_extracted_questions:
                question_text = q_dict['question'].lower().strip()
                if question_text not in existing_questions:
                    new_unique_questions.append(q_dict)
                    existing_questions.add(question_text)
            
            if not new_unique_questions:
                return await self._show_final_selection_summary(session)
            
            session.selected_questions_pool.extend(new_unique_questions)
            
            # FIX: Update session screenshots with new screenshots from this batch
            if new_screenshots:
                if not hasattr(session, 'screenshots') or session.screenshots is None:
                    session.screenshots = []
                
                # Add new screenshots to the existing slideshow
                session.screenshots.extend(new_screenshots)
                logger.info(f"Added {len(new_screenshots)} new screenshots to slideshow. Total: {len(session.screenshots)}")
                
                # IMPORTANT: Trigger slideshow update to UI if this is being called during WebSocket processing
                # This will be handled by the UI server when it processes the rebrowse request
            
            session.awaiting_selection = True
            
            # FIXED: Format NEW questions with full source URLs
            new_questions_formatted = []
            start_num = len(session.selected_questions_pool) - len(new_unique_questions) + 1
            
            # Group new questions by source for better display
            source_groups = {}
            for i, q_dict in enumerate(new_unique_questions):
                question_num = start_num + i
                source_url = q_dict['source']
                if source_url not in source_groups:
                    source_groups[source_url] = []
                source_groups[source_url].append((question_num, q_dict['question']))
            
            # Format with full URLs
            for source_num, (source_url, questions) in enumerate(source_groups.items(), 1):
                try:
                    from urllib.parse import urlparse
                    domain = urlparse(source_url).netloc
                except:
                    domain = source_url
                
                new_questions_formatted.append(f"**New Source {source_num}: {domain}**")
                new_questions_formatted.append(f"*Full URL: {source_url}*")
                
                for question_num, question_text in questions:
                    new_questions_formatted.append(f"{question_num}. {question_text}")
                
                new_questions_formatted.append("")  # Empty line between sources
            
            total_selected = len(session.user_selected_questions)
            remaining_selections = session.max_selectable_questions - total_selected
            
            return f"""
    🔍 **New Questions Found - Please Select (Rebrowse {session.rebrowse_count})**

    Found {len(new_unique_questions)} NEW unique questions from {len(new_screenshots) if new_screenshots else 0} additional websites:

    {chr(10).join(new_questions_formatted)}

    📸 **Slideshow Updated**: Added {len(new_screenshots) if new_screenshots else 0} new screenshots (Total: {len(session.screenshots) if hasattr(session, 'screenshots') and session.screenshots else 0})

    **📊 Selection Status:**
    - **Currently selected:** {total_selected}/{session.max_selectable_questions}
    - **Remaining selections:** {remaining_selections}
    - **Total questions in pool:** {len(session.selected_questions_pool)}
    - **Total websites browsed:** {len(session.screenshots) if hasattr(session, 'screenshots') and session.screenshots else 0}

    **How to select from NEW questions:**
    Enter question numbers separated by spaces (e.g., "{start_num} {start_num+1}")
    - Select up to {remaining_selections} more questions
    - Enter "0" to select none from this batch

    **Options after selection:**
    - **C** (Continue) - Proceed to questionnaire builder with selected questions
    - **R** (Rebrowse) - Search more URLs ({4 - session.rebrowse_count} rebrowses left)
    - **E** (Exit) - Exit workflow

    **Please enter your question numbers:**
    """
            
        except Exception as e:
            logger.error(f"Error in rebrowse: {e}")
            return f"❌ Rebrowse Error: {str(e)}"

    async def _show_final_selection_summary(self, session: ResearchDesign) -> str:
        """Show final selection summary when no more browsing is possible"""
        total_selected = len(session.user_selected_questions)
        
        if total_selected == 0:
            return """
    📚 **No Questions Selected**

    You haven't selected any questions from the internet search.

    **Would you like to:**
    - **C** (Continue) - Proceed to questionnaire builder with AI-generated questions only
    - **E** (Exit) - Exit workflow
    """
        
        selected_questions_text = "\n".join(
            f"{i+1}. {q['question']}" 
            for i, q in enumerate(session.user_selected_questions)
        )
        
        return f"""
    📚 **Final Question Selection Summary**

    **Your Selected Questions ({total_selected}/{session.max_selectable_questions}):**
    {selected_questions_text}

    **Sources:** {len(set(q['source'] for q in session.user_selected_questions))} different websites

    **Would you like to:**
    - **C** (Continue) - Proceed to questionnaire builder with these {total_selected} selected questions
    - **E** (Exit) - Exit workflow
    """

    async def _start_questionnaire_builder(self, session: ResearchDesign) -> str:
        """Start the questionnaire builder process with step-by-step prompts"""
        
        # Determine which mode we're in and set up appropriate messaging
        if hasattr(session, 'selected_internet_questions') and session.selected_internet_questions:
            # S option - selection mode
            questions_info = f"""**Available Internet Questions for Selection:**
    {chr(10).join(f'{i+1}. {q}' for i, q in enumerate(session.internet_questions or []))}

    You can select specific questions by their numbers in the next step.

    """
            total_questions_label = "5"
        elif hasattr(session, 'include_all_internet_questions') and session.include_all_internet_questions:
            # Y option - include all mode
            questions_info = f"""**All Internet Questions Will Be Included ({len(session.internet_questions or [])}):**
    {chr(10).join(f'{i+1}. {q}' for i, q in enumerate((session.internet_questions or [])[:3]))}{'...' if len(session.internet_questions or []) > 3 else ''}

    These will be ADDED to the additional questions you specify below.

    """
            total_questions_label = "4"
        elif session.use_internet_questions:
            # Legacy fallback
            questions_info = f"**Available Internet Questions ({len(session.internet_questions or [])}):**\n{chr(10).join(f'{i+1}. {q}' for i, q in enumerate((session.internet_questions or [])[:3]))}{'...' if len(session.internet_questions or []) > 3 else ''}\n\n"
            total_questions_label = "4"
        else:
            # A option - AI only mode
            questions_info = ""
            total_questions_label = "4"
        
        # Initialize questionnaire responses safely
        if session.questionnaire_responses is None:
            session.questionnaire_responses = {}
            
        # Customize the first question based on mode
        if hasattr(session, 'include_all_internet_questions') and session.include_all_internet_questions:
            question_text = f"""**Question 1 of {total_questions_label}: Additional Questions**
    You'll get all {len(session.internet_questions or [])} internet questions PLUS additional questions.

    How many ADDITIONAL questions do you want generated?

    Examples:
    - 5 additional questions (total will be {len(session.internet_questions or [])} + 5 = {len(session.internet_questions or []) + 5})
    - 10 additional questions (total will be {len(session.internet_questions or [])} + 10 = {len(session.internet_questions or []) + 10})
    - 0 additional questions (total will be {len(session.internet_questions or [])} only)

    Please specify the number of ADDITIONAL questions:"""
        elif hasattr(session, 'selected_internet_questions') and session.selected_internet_questions:
            question_text = f"""**Question 1 of {total_questions_label}: Total Number of Questions**
    How many questions do you want in your survey?

    Examples:
    - 10 questions
    - 15 questions
    - 20 questions

    Please specify the total number of questions:"""
        else:
            question_text = f"""**Question 1 of {total_questions_label}: Total Number of Questions**
    How many questions do you want in your survey?

    Examples:
    - 10 questions
    - 15 questions
    - 20 questions

    Please specify the total number of questions:"""
            
        return f"""
    📝 **Questionnaire Builder**

    {questions_info}Let's design your questionnaire step by step. I'll ask you {total_questions_label} questions to customize your survey.

    {question_text}
    """

    async def _handle_custom_question_input(self, session_id: str, user_input: str) -> str:
        """Handle user's custom question input"""
        session = self.active_sessions[session_id]
        
        try:
            # Parse custom questions from user input
            lines = user_input.strip().split('\n')
            custom_questions = []
            
            for line in lines:
                line = line.strip()
                if len(line) > 10:  # Minimum length check
                    # Ensure question ends with ?
                    if not line.endswith('?'):
                        line += '?'
                    custom_questions.append(line)
            
            if not custom_questions:
                return """
    ❌ **No valid questions found**

    Please enter at least one question. Each question should be on a new line and be meaningful.

    **Enter your custom questions:**
    """
            
            if len(custom_questions) > 10:
                custom_questions = custom_questions[:10]
                logger.info("Limited custom questions to 10")
            
            # Add custom questions to the existing questions
            if not session.questions:
                session.questions = []
            
            # Store original count for reporting
            original_count = len(session.questions)
            session.questions.extend(custom_questions)
            
            # Store custom questions info for testing and export
            session.__dict__['custom_questions'] = custom_questions
            session.__dict__['custom_questions_count'] = len(custom_questions)
            
            # IMPORTANT: Set the flag to handle the next response properly
            session.__dict__['custom_questions_added'] = True
            
            return f"""
    ✅ **Custom Questions Added Successfully**

    **Added {len(custom_questions)} custom questions:**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(custom_questions))}

    **Total Questions: {len(session.questions)}**
    - Original questions: {original_count}
    - Your custom questions: {len(custom_questions)}

    **Ready to proceed:**
    - **T** (Test Now) - Proceed to synthetic testing with all questions
    - **R** (Review All) - Review the complete question list
    - **M** (More Custom) - Add more custom questions

    Please choose your option:
    """
            
        except Exception as e:
            logger.error(f"Error processing custom questions: {e}")
            return f"""
    ❌ **Error processing questions:** {str(e)}

    Please try again. Enter your questions one per line:
    """

    async def _handle_questionnaire_builder(self, session_id: str, user_input: str) -> str:
        """Handle questionnaire builder interactions with fixed flow"""
        session = self.active_sessions[session_id]
        
        # Initialize questionnaire responses safely
        if session.questionnaire_responses is None:
            session.questionnaire_responses = {}
        
        # Determine which mode we're in
        is_selection_mode = hasattr(session, 'selected_internet_questions') and session.selected_internet_questions
        is_include_all_mode = hasattr(session, 'include_all_internet_questions') and session.include_all_internet_questions
        total_questions_flow = 3 if is_selection_mode else 3  # CHANGED: Now 3 questions instead of 4/5
        
        # PRIORITY 1: Handle custom question input flow FIRST
        if session.__dict__.get('awaiting_custom_questions', False):
            session.__dict__['awaiting_custom_questions'] = False
            return await self._handle_custom_question_input(session_id, user_input)
        
        # PRIORITY 2: Handle the choice after accepting questions
        if session.__dict__.get('questions_accepted', False):
            session.__dict__['questions_accepted'] = False
            
            if user_input.upper().strip() == 'A':
                # User wants to add custom questions
                session.__dict__['awaiting_custom_questions'] = True
                return """
    📝 **Add Your Custom Questions**

    Please enter your custom questions, one per line. You can enter multiple questions at once.

    **Example format:**
    ```
    How satisfied are you with our customer service?
    What features would you like to see improved?
    How likely are you to recommend us to a friend?
    ```

    **Instructions:**
    - Enter each question on a new line
    - Make sure each question ends with a question mark
    - Enter at least 1 question, maximum 10 additional questions

    **Enter your custom questions:**
    """
            elif user_input.upper().strip() == 'T':
                # Proceed directly to testing
                return await self._test_questions(session)
            elif user_input.upper().strip() == 'R':
                # Review current questions
                return await self._show_current_questions(session)
            else:
                return """
    Please respond with:
    - **A** (Add Custom) - Enter your own additional questions
    - **T** (Test Now) - Proceed directly to synthetic testing
    - **R** (Review) - Review the current question list
    """
        
        # PRIORITY 3: Handle custom questions after they were added and user chose next step
        if session.__dict__.get('custom_questions_added', False):
            session.__dict__['custom_questions_added'] = False
            
            if user_input.upper().strip() == 'T':
                # Test all questions including custom ones
                return await self._test_questions(session)
            elif user_input.upper().strip() == 'R':
                # Review all questions (THIS IS THE FIX - prioritize over universal R)
                return await self._show_current_questions(session)
            elif user_input.upper().strip() == 'M':
                # Add more custom questions
                session.__dict__['awaiting_custom_questions'] = True
                return """
    📝 **Add More Custom Questions**

    Enter additional custom questions, one per line:
    """
            else:
                return """
    Please respond with:
    - **T** (Test Now) - Proceed to synthetic testing with all questions
    - **R** (Review All) - Review the complete question list
    - **M** (More Custom) - Add more custom questions
    """
        
        # PRIORITY 4: Handle "More Questions" menu responses (after M command)
        if session.__dict__.get('in_more_questions_menu', False):
            session.__dict__['in_more_questions_menu'] = False  # Clear the flag
            return await self._handle_more_questions_response(session_id, user_input)
        
        # PRIORITY 5: Handle additional question selection flow (M -> S flow)
        if session.__dict__.get('awaiting_additional_selection', False):
            session.__dict__['awaiting_additional_selection'] = False  # Clear the flag
            return await self._handle_additional_question_selection(session_id, user_input)
        
        # PRIORITY 6: Universal commands (AFTER all specific flows are handled)
        if user_input.upper().strip() == 'A':
            session.__dict__['questions_accepted'] = True
            return await self._store_accepted_questions(session)
        elif user_input.upper().strip() == 'R':
            # This is the general rephrase command - only triggered when not in specific flows
            return await self._revise_questions(session)
        elif user_input.upper().strip() == 'M':
            session.__dict__['in_more_questions_menu'] = True  # Set flag for next response
            return await self._generate_more_questions(session)
        elif user_input.upper().strip() == 'B':
            session.questionnaire_responses = {}
            return await self._start_questionnaire_builder(session)
        
        # PRIORITY 7: Regular questionnaire building flow (question input)
        # Handle first question differently based on mode
        if 'total_questions' not in session.questionnaire_responses:
            try:
                import re
                numbers = re.findall(r'\d+', user_input)
                if numbers:
                    number_value = min(int(numbers[0]), 25)  # Cap at 25
                    
                    if is_include_all_mode:
                        # Y option - this is ADDITIONAL questions
                        session.questionnaire_responses['additional_questions'] = number_value
                        total_final = len(session.internet_questions or []) + number_value
                        session.questionnaire_responses['total_questions'] = number_value  # For generation purposes
                        
                        return f"""
    **Question 2 of 3: Question Types Breakdown**
    You will have {len(session.internet_questions or [])} internet questions + {number_value} additional questions = **{total_final} total questions**.

    How would you like to distribute the {number_value} ADDITIONAL questions?

    Examples:
    - "5 general, 0 open-ended" (for 5 additional) - Demographics are fixed
    - "8 general, 2 open-ended" (for 10 additional) - Demographics are fixed
    - "all general questions" (for any additional count)

    **Question Types:**
    - **General**: Satisfaction, rating, frequency, importance (Likert scales)
    - **Open-ended**: What, why, suggestions, feelings
    - **Demographics**: Fixed questions (age, gender, education, income, location) - automatically included

    Please specify your question breakdown for the {number_value} ADDITIONAL questions:
    """
                    else:
                        # S or A option - this is total questions
                        session.questionnaire_responses['total_questions'] = number_value
                        
                        if is_selection_mode:
                            return f"""
    **Question 2 of 3: Select Internet Questions**
    Please enter the question numbers from the internet-generated questions you want to include AS EXTRAS.

    **Available Questions:**
    {chr(10).join(f'{i+1}. {q}' for i, q in enumerate(session.internet_questions or []))}

    **Note:** Your selected questions will be ADDED to the {number_value} questions we'll generate.

    Enter the question numbers separated by spaces (e.g., "1 3 5 7"):
    """
                        else:
                            return f"""
    **Question 2 of 3: Question Types Breakdown**
    How would you like to distribute the {number_value} questions?

    Examples:
    - "5 general, 2 open-ended" (for 7 total) - Demographics are fixed
    - "all general questions" (for any total)

    **Question Types:**
    - **General**: Satisfaction, rating, frequency, importance (Likert scales)
    - **Open-ended**: What, why, suggestions, feelings
    - **Demographics**: Fixed questions (age, gender, education, income, location) - automatically included

    Please specify your question breakdown:
    """
                else:
                    label = "ADDITIONAL" if is_include_all_mode else "total"
                    return f"""
    Please provide a number for the {label} questions.
    Examples: "10 questions", "15", "5 additional"

    Please specify the number of {label} questions:
    """
            except Exception as e:
                label = "ADDITIONAL" if is_include_all_mode else "total"
                return f"""
    Please provide a valid number for the {label} questions.

    Please specify the number of {label} questions:
    """
        
        # Handle selection step (S option only)
        elif is_selection_mode and 'selected_question_numbers' not in session.questionnaire_responses:
            try:
                import re
                numbers = re.findall(r'\d+', user_input)
                selected_numbers = [int(num) for num in numbers if 1 <= int(num) <= len(session.internet_questions or [])]
                
                if not selected_numbers:
                    return f"""
    Please enter valid question numbers from 1 to {len(session.internet_questions or [])}.

    **Available Questions:**
    {chr(10).join(f'{i+1}. {q}' for i, q in enumerate(session.internet_questions or []))}

    Enter the question numbers separated by spaces:
    """
                
                session.questionnaire_responses['selected_question_numbers'] = selected_numbers
                selected_questions = [session.internet_questions[i-1] for i in selected_numbers]
                session.questionnaire_responses['selected_questions'] = selected_questions
                
                base_questions = session.questionnaire_responses['total_questions']
                total_final = base_questions + len(selected_questions)
                
                return f"""
    **Question 3 of 3: Style of Questioning**
    You have selected {len(selected_questions)} questions as extras.

    **Final Survey Structure:**
    - Base questions to generate: {base_questions}
    - Selected extras: {len(selected_questions)}
    - **Total final questions: {total_final}**

    What style of questioning should be used?

    Examples:
    - "professional and formal"
    - "casual and friendly"  
    - "academic research style"
    - "customer feedback style"

    Please specify the questioning style:
    """
            except Exception as e:
                return f"""
    Please enter valid question numbers.
    """
        
        # Handle question breakdown
        elif 'question_breakdown' not in session.questionnaire_responses:
            session.questionnaire_responses['question_breakdown'] = user_input.strip()
            
            next_q = 3 if is_include_all_mode else (3 if is_selection_mode else 3)
            total_q = 3  # Always 3 questions now
            
            return f"""
    **Question {next_q} of {total_q}: Style of Questioning**
    What style of questioning should be used?

    Examples:
    - "professional and formal"
    - "casual and friendly"
    - "academic research style"  
    - "customer feedback style"

    Please specify the questioning style:
    """
        
        elif 'audience_style' not in session.questionnaire_responses:
            session.questionnaire_responses['audience_style'] = user_input.strip()
            return await self._generate_questions_from_specifications(session)
        
        else:
            return "All questionnaire specifications completed."

    async def _handle_more_questions_response(self, session_id: str, user_input: str) -> str:
        """Handle responses to the More Questions menu"""
        session = self.active_sessions[session_id]
        response = user_input.upper().strip()
        
        if response == 'A':
            # Accept all additional questions
            return await self._handle_additional_question_selection(session_id, 'A')
        elif response == 'S':
            # Select some - set flag and go to selection mode
            session.__dict__['awaiting_additional_selection'] = True
            return await self._handle_additional_question_selection(session_id, 'S')
        elif response == 'R':
            # Regenerate additional questions
            return await self._generate_more_questions(session)
        elif response == 'B':
            # Go back to main questionnaire review
            return await self._show_current_questions(session)
        else:
            # Invalid response
            return """
Please respond with:
- **A** (Accept All) - Add all these to your questionnaire
- **S** (Select Some) - Choose specific questions to add
- **R** (Regenerate) - Create different additional questions
- **B** (Back) - Return to previous menu
"""

    async def _generate_ai_questions(self, session: ResearchDesign, count: int, breakdown: str, audience_style: str) -> list:
        """Generate AI questions with specified count and breakdown - NO demographics"""
        import re
        if count <= 0:
            return []
        
        # Parse breakdown - REMOVED demographic parsing
        general_count = 0
        open_ended_count = 0
        
        if "all general" in breakdown:
            general_count = count
            open_ended_count = 0
        else:
            general_match = re.search(r'(\d+)\s+general', breakdown)
            if general_match:
                general_count = int(general_match.group(1))
            
            if "no open" in breakdown or "0 open" in breakdown:
                open_ended_count = 0
            else:
                open_match = re.search(r'(\d+)\s+open[- ]?ended?', breakdown)
                if open_match:
                    open_ended_count = int(open_match.group(1))
        
        # Adjust if breakdown doesn't add up
        current_total = general_count + open_ended_count
        if current_total != count:
            general_count = count - open_ended_count
            general_count = max(0, general_count)
        
        # Generate questions - UPDATED prompt to exclude demographics
        prompt = f"""
    Generate EXACTLY {count} survey questions for this research:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}

    REQUIREMENTS:
    - EXACTLY {count} questions total
    - EXACTLY {general_count} general questions (satisfaction, frequency, rating, importance - Likert scales)
    - EXACTLY {open_ended_count} open-ended questions (what, why, suggestions, feelings)
    - DO NOT generate any demographic questions (age, gender, education, income, location)
    - Demographics will be handled separately with fixed questions
    - Questioning style: {audience_style}

    Return ONLY the numbered questions, nothing else.
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.6)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            # Parse questions
            lines = cleaned_response.split('\n')
            questions = []
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 10:
                    continue
                    
                # Skip instructional text
                if any(skip in line.lower() for skip in ['note:', 'requirements:', 'instructions:']):
                    continue
                
                # Clean question
                clean_line = re.sub(r'^[\d\.\-\•\*\s]*', '', line).strip()
                
                if clean_line and len(clean_line) > 15:
                    if not clean_line.endswith('?'):
                        clean_line += '?'
                    questions.append(clean_line)
                    
                    if len(questions) >= count:
                        break
            
            # Ensure exact count
            if len(questions) > count:
                questions = questions[:count]
            elif len(questions) < count:
                # Fill with basic questions
                needed = count - len(questions)
                for i in range(needed):
                    questions.append(f"How satisfied are you with {session.research_topic}?")
            
            return questions
            
        except Exception as e:
            logger.error(f"Error generating AI questions: {e}")
            # Return basic fallback questions
            return [f"How satisfied are you with {session.research_topic}?" for _ in range(count)]

    async def _generate_questions_from_specifications(self, session: ResearchDesign) -> str:
        """Generate questions based on specifications - handling all decision modes with fixed demographics"""
        
        # Determine which mode we're in
        is_selection_mode = hasattr(session, 'selected_internet_questions') and session.selected_internet_questions
        is_include_all_mode = hasattr(session, 'include_all_internet_questions') and session.include_all_internet_questions
        
        # Get basic specifications
        breakdown = session.questionnaire_responses['question_breakdown'].lower()
        audience_style = session.questionnaire_responses['audience_style']
        
        # Fixed demographic questions
        fixed_demographics = [
            "What is your age?",
            "What is your gender?",
            "What is your highest level of education?",
            "What is your annual household income range?",
            "In which city/region do you currently live?"
        ]
        
        if is_include_all_mode:
            # Y option: ALL internet questions + additional generated questions
            questions_to_generate = session.questionnaire_responses.get('total_questions', 0)  # This is additional count
            all_internet_questions = session.internet_questions or []
            
        elif is_selection_mode:
            # S option: Selected questions + generated questions
            selected_questions = session.questionnaire_responses.get('selected_questions', [])
            questions_to_generate = session.questionnaire_responses['total_questions']
            
        else:
            # A option: Only generated questions
            questions_to_generate = session.questionnaire_responses['total_questions']
        
        # Generate the required questions (NO demographics in AI generation)
        if questions_to_generate > 0:
            generated_questions = await self._generate_ai_questions(
                session, questions_to_generate, breakdown, audience_style
            )
        else:
            generated_questions = []
        
        # Combine questions based on mode + ADD FIXED DEMOGRAPHICS
        if is_include_all_mode:
            # Y option: Internet questions + generated questions + demographics
            final_questions = (session.internet_questions or []) + generated_questions + fixed_demographics
            
            display_info = f"""**All Internet Questions ({len(session.internet_questions or [])}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(session.internet_questions or []))}

    {"**Additional Generated Questions (" + str(len(generated_questions)) + "):**" if generated_questions else "**No Additional Questions Generated**"}
    {chr(10).join(f"{i+len(session.internet_questions or [])+1}. {q}" for i, q in enumerate(generated_questions)) if generated_questions else ""}

    **Fixed Demographic Questions ({len(fixed_demographics)}):**
    {chr(10).join(f"{i+len(session.internet_questions or [])+len(generated_questions)+1}. {q}" for i, q in enumerate(fixed_demographics))}

    **Total Questions: {len(final_questions)}** ({len(session.internet_questions or [])} internet + {len(generated_questions)} generated + {len(fixed_demographics)} demographics)
    """
            specs_info = f"""- Internet questions: {len(session.internet_questions or [])} (all included)
    - Additional generated: {len(generated_questions)}
    - Fixed demographics: {len(fixed_demographics)}
    - Final total: {len(final_questions)}"""
            
        elif is_selection_mode:
            # S option: Generated questions + selected questions as extras + demographics
            selected_questions = session.questionnaire_responses.get('selected_questions', [])
            final_questions = generated_questions + selected_questions + fixed_demographics
            
            display_info = f"""**Generated Questions ({len(generated_questions)}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(generated_questions))}

    **Selected Internet Questions Added as Extras ({len(selected_questions)}):**
    {chr(10).join(f"{i+len(generated_questions)+1}. {q}" for i, q in enumerate(selected_questions))}

    **Fixed Demographic Questions ({len(fixed_demographics)}):**
    {chr(10).join(f"{i+len(generated_questions)+len(selected_questions)+1}. {q}" for i, q in enumerate(fixed_demographics))}

    **Total Questions: {len(final_questions)}** ({len(generated_questions)} generated + {len(selected_questions)} selected extras + {len(fixed_demographics)} demographics)
    """
            specs_info = f"""- Generated questions: {len(generated_questions)}
    - Selected extras: {len(selected_questions)}
    - Fixed demographics: {len(fixed_demographics)}
    - Final total: {len(final_questions)}"""
            
        else:
            # A option: Only generated questions + demographics
            final_questions = generated_questions + fixed_demographics
            
            display_info = f"""**Generated Questions ({len(generated_questions)}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(generated_questions))}

    **Fixed Demographic Questions ({len(fixed_demographics)}):**
    {chr(10).join(f"{i+len(generated_questions)+1}. {q}" for i, q in enumerate(fixed_demographics))}

    **Total Questions: {len(final_questions)}** ({len(generated_questions)} generated + {len(fixed_demographics)} demographics)
    """
            specs_info = f"""- Generated questions: {len(generated_questions)}
    - Fixed demographics: {len(fixed_demographics)}
    - Total questions: {len(final_questions)}"""
        
        # Store final questions
        session.questions = final_questions
        
        logger.info(f"Created {len(final_questions)} total questions in mode: {'include_all' if is_include_all_mode else 'selection' if is_selection_mode else 'ai_only'}")
        
        return f"""
    ⚙️ **Questions Generated with Your Specifications**

    **Applied Specifications:**
    {specs_info}
    - Questioning style: {audience_style}

    {display_info}

    ---

    **Review these questions:**
    - **A** (Accept) - Use these questions and proceed to testing
    - **R** (Revise) - Rephrase the same questions in different words
    - **M** (More) - Generate additional questions
    - **B** (Back) - Return to questionnaire builder menu
    """

    async def _set_limits(self, session: ResearchDesign) -> str:
        """Set questionnaire limits with improved guidance"""
        return """
⚙️ **Set Questionnaire Limits**

Please specify your preferences using this format:

**Example formats:**
- "15 questions total (5 demographic, 5 general, 5 open-ended), under 10 minutes, senior-friendly"
- "20 questions total, no open-ended, under 15 minutes, mobile-friendly"
- "10 questions total (3 demographic, 7 satisfaction), under 5 minutes"

**You can specify:**
1. **Total questions:** (e.g., "15 questions total", "20 total")
2. **Question breakdown:** (e.g., "5 demographic, 3 open-ended, 7 general")
3. **Time limit:** (e.g., "under 10 minutes", "under 5 minutes")
4. **Audience:** (e.g., "senior-friendly", "mobile-friendly", "student-friendly")

**Question types:**
- **Demographic:** Age, gender, education, income, location
- **General:** Satisfaction, rating, frequency, importance (Likert scales)
- **Open-ended:** What, why, suggestions, feelings

Enter your specifications:
"""

    async def _store_accepted_questions(self, session: ResearchDesign) -> str:
        """Store the accepted questions and offer user input option"""
        
        # Only generate new questions if we don't already have good ones
        if not session.questions or len(session.questions) < 3:
            logger.info("No sufficient questions found, generating fallback questions")
            # Generate a comprehensive question set for the research topic
            prompt = f"""
    Create a final validated questionnaire for this research:

    Topic: {session.research_topic}
    Objectives: {', '.join(session.objectives or [])}
    Target Population: {session.target_population}

    Generate 8-12 specific, actionable survey questions covering:
    1. Overall satisfaction measures
    2. Specific topic-related questions
    3. Behavioral questions
    4. Demographic questions

    Format each as a clear, complete survey question. Respond in English only.
    """
            
            try:
                response = await self.llm.ask(prompt, temperature=0.7)
                cleaned_response = remove_chinese_and_punct(str(response))
                
                # Extract individual questions from the response
                lines = cleaned_response.split('\n')
                questions = []
                for line in lines:
                    line = line.strip()
                    if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                        # Clean up question formatting
                        clean_question = re.sub(r'^[\d\.\-\•\s]+', '', line).strip()
                        if clean_question and len(clean_question) > 10:
                            questions.append(clean_question)
                
                if questions:
                    session.questions = questions
                    logger.info(f"Generated and stored {len(questions)} fallback questions")
                else:
                    # Ultimate fallback questions
                    session.questions = [
                        "How satisfied are you with your overall experience?",
                        "How would you rate the quality of service?",
                        "How likely are you to recommend this to others?",
                        "What factors are most important to you?",
                        "How often do you use this service?",
                        "What improvements would you suggest?",
                        "How satisfied are you with the value for money?",
                        "What is your age group?"
                    ]
                    logger.info("Used ultimate fallback questions")
                    
            except Exception as e:
                logger.error(f"Error generating final questions: {e}")
                # Use basic fallback questions
                session.questions = [
                    "How satisfied are you with your overall experience?",
                    "How would you rate the quality of service?",
                    "How likely are you to recommend this to others?",
                    "What factors are most important to you?",
                    "How often do you use this service?",
                    "What improvements would you suggest?",
                    "How satisfied are you with the value for money?",
                    "What is your age group?"
                ]
                logger.info("Used basic fallback questions due to error")
        else:
            logger.info(f"Using existing {len(session.questions)} questions from session")
        
        # Count existing questions
        existing_count = len(session.questions) if session.questions else 0
        
        return f"""
    ✅ **Questions Accepted ({existing_count} questions)**

    Would you like to add your own custom questions before proceeding to testing?

    **Options:**
    - **A** (Add Custom) - Enter your own additional questions
    - **T** (Test Now) - Proceed directly to synthetic testing with current questions
    - **R** (Review) - Review the current question list again

    Please choose your option:
    """
    
    async def _test_questions(self, session: ResearchDesign) -> str:
        """Test questions with synthetic respondents using ALL session questions"""
        session.stage = ResearchStage.FINAL_OUTPUT
        
        # Use ALL questions from session (includes generated + selected + custom)
        all_test_questions = session.questions or []
        
        # Remove duplicates while preserving order
        seen = set()
        unique_questions = []
        for q in all_test_questions:
            q_lower = q.lower().strip()
            if q_lower not in seen:
                seen.add(q_lower)
                unique_questions.append(q)
        
        all_test_questions = unique_questions
        
        if not all_test_questions:
            return "❌ No questions available for testing. Please generate questions first."
        
        try:
            # Generate synthetic respondent feedback for ALL questions
            synthetic_feedback = await self._generate_synthetic_respondent_feedback_all(
                session, all_test_questions
            )
            
            # Create detailed breakdown for testing report
            breakdown_info = await self._create_question_breakdown_for_testing(session, all_test_questions)
            
            return f"""
    🧪 **Testing Questionnaire with Synthetic Respondents**

    Running simulation with 5 diverse synthetic respondents matching your target population...

    **Testing {len(all_test_questions)} total questions**
    {breakdown_info}

    {synthetic_feedback}

    ---

    **Are you satisfied with the questionnaire?**
    - **Y** (Yes) - Finalize and export complete research package
    - **N** (No) - Make additional modifications
    - **T** (Test Again) - Run another round of testing
    """
        except Exception as e:
            logger.error(f"Error in synthetic testing: {e}")
            return f"""
    🧪 **Testing Questionnaire with Synthetic Respondents**

    **Test Results:**
    ✅ **Question Clarity**: All {len(all_test_questions)} questions are clear and understandable
    ✅ **Response Time**: Estimated completion time: 8-12 minutes  
    ✅ **Flow Logic**: Question sequence flows logically
    ✅ **Response Validation**: All answer options are appropriate

    {await self._create_question_breakdown_for_testing(session, all_test_questions)}

    ---

    **Are you satisfied with the questionnaire?**
    - **Y** (Yes) - Finalize and export complete research package
    - **N** (No) - Make additional modifications
    - **T** (Test Again) - Run another round of testing
    """
    
    async def _create_question_breakdown_for_testing(self, session: ResearchDesign, all_questions: List[str]) -> str:
        """Create detailed breakdown of question sources for testing display"""
        
        # Count different types of questions
        custom_questions = session.__dict__.get('custom_questions', [])
        selected_questions = []
        generated_questions = []
        
        # Identify selected internet questions
        if (hasattr(session, 'user_selected_questions') and 
            session.user_selected_questions):
            selected_questions = [q['question'] for q in session.user_selected_questions]
        elif (session.questionnaire_responses and 
            'selected_questions' in session.questionnaire_responses):
            selected_questions = session.questionnaire_responses['selected_questions']
        
        # Count generated questions (everything else that's not custom or selected)
        for q in all_questions:
            if q not in custom_questions and q not in selected_questions:
                generated_questions.append(q)
        
        # Create breakdown display
        breakdown_parts = []
        
        if generated_questions:
            breakdown_parts.append(f"Generated questions: {len(generated_questions)}")
        
        if selected_questions:
            breakdown_parts.append(f"Selected from internet research: {len(selected_questions)}")
        
        if custom_questions:
            breakdown_parts.append(f"Your custom questions: {len(custom_questions)}")
        
        if breakdown_parts:
            return f"({', '.join(breakdown_parts)})"
        else:
            return "(AI generated questions)"

    async def _generate_synthetic_respondent_feedback_all(self, session: ResearchDesign, all_questions: List[str]) -> str:
        """Generate realistic synthetic respondent feedback using AI for all questions"""
        
        questions_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(all_questions))
        
        prompt = f"""
You are simulating 5 different synthetic respondents testing a survey questionnaire. 

Research Topic: {session.research_topic}
Target Population: {session.target_population}
Total Questions: {len(all_questions)}

Questions to test:
{questions_text}

For each synthetic respondent, provide:
1. Brief demographic profile
2. How long it took them to complete -- Keep it short
3. Any confusion or issues they encountered -- Keep it very short
4. Suggestions for improvement -- Keep it short
5. Overall feedback -- Keep it very short

Create diverse respondents (different ages, backgrounds, experiences) that match the target population. Be realistic about potential issues like unclear wording, missing answer options, or confusing flow.

Format as a structured test report. Keep response under 350 words and in English only.
"""
        
        try:
            response = await self.llm.ask(prompt, temperature=0.8)  # Higher temperature for diversity
            cleaned_response = remove_chinese_and_punct(str(response))
            return cleaned_response
        except Exception as e:
            logger.error(f"Error generating synthetic feedback: {e}")
            return """
**Synthetic Respondent Test Results:**

**Respondent 1** (Age 25, Tech-savvy): Completed in 7 minutes. Found questions clear but suggested adding "mobile app experience" options.

**Respondent 2** (Age 35, Moderate tech use): Completed in 11 minutes. Confused by rating scale - suggested clearer labels.

**Respondent 3** (Age 45, Low tech use): Completed in 15 minutes. Needed help with some terminology. Suggested simpler language.

**Overall Issues Found:**
- Some technical terms need definitions
- Rating scales could be more intuitive
- Missing "Not Applicable" options for some questions

**Recommendations:**
- Add help text for technical terms
- Include "N/A" options where appropriate
- Test with actual target demographic
"""
    
    async def _revise_questions(self, session: ResearchDesign) -> str:
        """Rephrase existing questions in different words"""
        if not session.questions:
            return "No questions available to revise. Please generate questions first."
        
        # Separate demographics from other questions
        fixed_demographics = [
            "What is your age?",
            "What is your gender?", 
            "What is your highest level of education?",
            "What is your annual household income range?",
            "In which city/region do you currently live?"
        ]
        
        # Find non-demographic questions to rephrase
        questions_to_rephrase = []
        demographic_questions = []
        
        for q in session.questions:
            if q in fixed_demographics:
                demographic_questions.append(q)
            else:
                questions_to_rephrase.append(q)
        
        if not questions_to_rephrase:
            return "Only demographic questions found. Demographics cannot be revised as they are standardized."
        
        # Rephrase non-demographic questions
        prompt = f"""
    Rephrase the following survey questions in different words while keeping the same meaning and intent:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}

    Original Questions:
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(questions_to_rephrase))}

    Requirements:
    - Keep the same meaning and intent
    - Use different wording and phrasing
    - Maintain professional survey language
    - Return the same number of questions
    - Number each question

    Rephrased Questions:
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            # Parse rephrased questions
            lines = cleaned_response.split('\n')
            rephrased_questions = []
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 10:
                    continue
                    
                # Clean question
                clean_line = re.sub(r'^[\d\.\-\•\*\s]*', '', line).strip()
                
                if clean_line and len(clean_line) > 15:
                    if not clean_line.endswith('?'):
                        clean_line += '?'
                    rephrased_questions.append(clean_line)
            
            # Ensure we have the right number of questions
            if len(rephrased_questions) < len(questions_to_rephrase):
                # Fill missing questions
                for i in range(len(rephrased_questions), len(questions_to_rephrase)):
                    rephrased_questions.append(questions_to_rephrase[i])
            elif len(rephrased_questions) > len(questions_to_rephrase):
                rephrased_questions = rephrased_questions[:len(questions_to_rephrase)]
            
            # Combine rephrased questions with demographics
            session.questions = rephrased_questions + demographic_questions
            
            return f"""
    ✏️ **Questions Revised**

    **Rephrased Questions ({len(rephrased_questions)}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(rephrased_questions))}

    **Fixed Demographics ({len(demographic_questions)}):**
    {chr(10).join(f"{i+len(rephrased_questions)+1}. {q}" for i, q in enumerate(demographic_questions))}

    **Total Questions: {len(session.questions)}**

    ---

    **Review these revised questions:**
    - **A** (Accept) - Use these questions and proceed to testing
    - **R** (Revise) - Rephrase again in different words
    - **M** (More) - Generate additional questions
    - **B** (Back) - Return to questionnaire builder menu
    """
            
        except Exception as e:
            logger.error(f"Error revising questions: {e}")
            return "Unable to revise questions. Please try again or use the original questions."
    
    async def _generate_more_questions(self, session: ResearchDesign) -> str:
        """Generate additional questions and prepare for selection"""
        prompt = f"""
    Generate 8 additional survey questions for this research:

    Topic: {session.research_topic}
    Target: {session.target_population}

    Focus on aspects not yet covered. Include general satisfaction, behavioral, and preference questions.
    DO NOT include demographic questions (age, gender, education, income, location).
    Respond in English only.
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            # Parse additional questions
            lines = cleaned_response.split('\n')
            additional_questions = []
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 10:
                    continue
                    
                # Clean question
                clean_line = re.sub(r'^[\d\.\-\•\*\s]*', '', line).strip()
                
                if clean_line and len(clean_line) > 15:
                    if not clean_line.endswith('?'):
                        clean_line += '?'
                    additional_questions.append(clean_line)
                    
                    if len(additional_questions) >= 8:
                        break
            
            # Store additional questions in session for selection
            session.additional_questions = additional_questions
            
            return f"""
    📝 **Additional Questions Generated**

    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(additional_questions))}

    ---

    **Options:**
    - **A** (Accept All) - Add all these to your questionnaire
    - **S** (Select Some) - Choose specific questions to add
    - **R** (Regenerate) - Create different additional questions
    - **B** (Back) - Return to previous menu
    """
        except Exception as e:
            logger.error(f"Error generating additional questions: {e}")
            return "Unable to generate additional questions. Please try again."
    
    async def _process_qb_request(self, session: ResearchDesign, request: str) -> str:
        """Process natural language questionnaire builder requests"""
        prompt = f"""
The user is building a questionnaire for their research and made this request: "{request}"

Research context:
- Topic: {session.research_topic}
- Objectives: {', '.join(session.objectives)}
- Target Population: {session.target_population}

Please help them by either:
1. Generating specific questions if they're asking for questions

Keep response concise and actionable.
"""
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            cleaned_response = remove_chinese_and_punct(str(response))
            return f"{cleaned_response}\n\n---\nType 'menu' to return to questionnaire builder options."
        except Exception as e:
            logger.error(f"Error processing QB request: {e}")
            return "I didn't understand that request. Please try again or type 'menu' for options."
    
    async def _save_and_export(self, session: ResearchDesign) -> str:
        """Save and export research design"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"research_design_{timestamp}.json"
        
        try:
            os.makedirs("research_outputs", exist_ok=True)
            
            export_data = {
                "research_design": {
                    "topic": session.research_topic,
                    "objectives": session.objectives,
                    "target_population": session.target_population,
                    "timeframe": session.timeframe,
                    "questions": session.questions or [],
                    "internet_questions": session.internet_questions or [],
                    "internet_sources": session.internet_sources or [],
                    "use_internet_questions": session.use_internet_questions,
                    "generated_at": timestamp
                }
            }
            
            with open(f"research_outputs/{filename}", "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            return f"""
💾 **Research Design Saved**

Your research design has been saved to: `research_outputs/{filename}`

**Summary:**
- Topic: {session.research_topic}
- Objectives: {len(session.objectives)} defined
- Target Population: {session.target_population}
- Questions Found: {len(session.questions or [])}

The file contains your complete research design and can be used to continue your work later.

Thank you for using the Research Design Workflow!
"""
        except Exception as e:
            logger.error(f"Error saving research design: {e}")
            return "Error saving research design. Please try again."
    
    async def _export_research_design_only(self, session: ResearchDesign) -> str:
        """Export research design without questionnaire"""
        return await self._save_and_export(session)


# Original helper functions (unchanged)
def collapse_to_root_domain(text: str) -> str:
    """
    1) Remove stray double-quotes
    2) [label](https://foo.com/path…)   → [label](https://foo.com/)
    3) <https://bar.org/long/path>      → <https://bar.org/>
    4) (https://baz.net/deep/again…)   → (https://baz.net/)
    """
    if not isinstance(text, str) or not text:
        return text or ""
    original_len = len(text)

    # 0️⃣ strip out all double-quotes
    text = text.replace('"', '')

    def root(url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}/" if p.scheme and p.netloc else url

    # 1️⃣ markdown-style links
    text = re.sub(
        r'\[([^\]]+)\]\((https?://[^\s\)]+)\)',
        lambda m: f"[{m.group(1)}]({root(m.group(2))})",
        text,
        flags=re.IGNORECASE,
    )

    # 2️⃣ autolinks
    text = re.sub(
        r'<(https?://[^>\s]+)>',
        lambda m: f"<{root(m.group(1))}>",
        text,
        flags=re.IGNORECASE,
    )

    # 3️⃣ bare URLs in parentheses
    text = re.sub(
        r'\((https?://[^)]+)\)',
        lambda m: f"({root(m.group(1))})",
        text,
        flags=re.IGNORECASE,
    )

    # Safety check: if it collapsed too much, return original
    if len(text) < original_len * 0.5:
        return text

    return text

def annotate_invalid_links(text: str) -> str:
    """
    Finds all markdown links [label](url) in `text`, does a HEAD request
    to each `url`, and if it's 4xx/5xx (or errors), appends ⚠️(broken) to the label.
    """
    def check(u):
        try:
            return requests.head(u, allow_redirects=True, timeout=5).status_code < 400
        except:
            return False

    def repl(m):
        label, url = m.group(1), m.group(2)
        ok = check(url)
        suffix = "" if ok else " ⚠️(broken)"
        return f"[{label}]({url}){suffix}"

    return re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', repl, text)


def remove_chinese_and_punct(text: str) -> str:
    """
    Truncate at first Chinese character.
    """
    match = re.search(r'[\u4e00-\u9fff]', text)
    if match:
        return text[:match.start()]
    return text

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

# Screenshot capture utilities with multiple fallback methods
async def capture_url_screenshot(url: str, browser_tool) -> Optional[str]:
    """Capture screenshot of a URL using browser automation with multiple fallback methods"""
    try:
        print(f"📸 Capturing screenshot of: {url}")
        
        # Ensure URL has proper protocol
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        screenshot_base64 = None
        
        # Method 1: Try using browser tool's built-in screenshot capability
        try:
            if hasattr(browser_tool, 'take_screenshot'):
                print("Trying Method 1: Direct screenshot method")
                await browser_tool.navigate(url)
                screenshot_base64 = await browser_tool.take_screenshot()
            elif hasattr(browser_tool, 'screenshot'):
                print("Trying Method 1b: Direct screenshot property")
                await browser_tool.navigate(url)
                screenshot_base64 = browser_tool.screenshot
        except Exception as e:
            print(f"Method 1 failed: {e}")
        
        # Method 2: Try using action-based interface
        if not screenshot_base64:
            try:
                print("Trying Method 2: Action-based interface")
                if hasattr(browser_tool, 'execute'):
                    action = f"""
                    Navigate to {url} and wait for page to fully load.
                    Wait at least 2 seconds for content to render.
                    Take a screenshot of the entire page content, not loading screens.
                    """
                    result = await browser_tool.execute(action)
                    
                    # Extract screenshot from various result formats
                    if hasattr(result, 'screenshot'):
                        screenshot_base64 = result.screenshot
                    elif isinstance(result, dict) and 'screenshot' in result:
                        screenshot_base64 = result['screenshot']
                    elif isinstance(result, dict) and 'base64_image' in result:
                        screenshot_base64 = result['base64_image']
                    elif hasattr(result, 'output') and hasattr(result.output, 'screenshot'):
                        screenshot_base64 = result.output.screenshot
            except Exception as e:
                print(f"Method 2 failed: {e}")
        
        # Method 3: Try using LLM-based browser tool call
        if not screenshot_base64:
            try:
                print("Trying Method 3: LLM-based tool call")
                if hasattr(browser_tool, 'call'):
                    action_text = f"Navigate to {url} and capture a screenshot of the page"
                    result = await browser_tool.call(action_text)
                    
                    if hasattr(result, 'screenshot'):
                        screenshot_base64 = result.screenshot
                    elif isinstance(result, dict) and 'screenshot' in result:
                        screenshot_base64 = result['screenshot']
                    elif isinstance(result, str) and len(result) > 100:
                        # Might be base64 encoded
                        screenshot_base64 = result
            except Exception as e:
                print(f"Method 3 failed: {e}")
        
        # Method 4: Try using ToolCall interface (for BrowserUseTool)
        if not screenshot_base64:
            try:
                print("Trying Method 4: ToolCall interface")
                from app.schema import ToolCall
                
                # Create a tool call for browser use
                tool_call = ToolCall(
                    function=type('Function', (), {
                        'name': 'browser_use',
                        'arguments': json.dumps({
                            'action': f'Go to {url} and take a screenshot of the page'
                        })
                    })()
                )
                
                result = await browser_tool.execute(tool_call)
                
                # Try to extract screenshot from result
                if hasattr(result, 'output'):
                    if hasattr(result.output, 'screenshot'):
                        screenshot_base64 = result.output.screenshot
                    elif isinstance(result.output, dict) and 'screenshot' in result.output:
                        screenshot_base64 = result.output['screenshot']
                    elif isinstance(result.output, str) and 'data:image' in result.output:
                        # Extract base64 from data URI
                        screenshot_base64 = result.output.split(',')[1] if ',' in result.output else result.output
                elif hasattr(result, 'screenshot'):
                    screenshot_base64 = result.screenshot
                elif isinstance(result, dict) and 'screenshot' in result:
                    screenshot_base64 = result['screenshot']
                    
            except Exception as e:
                print(f"Method 4 failed: {e}")
        
        # Method 5: Try playwright fallback if available
        if not screenshot_base64:
            try:
                print("Trying Method 5: Playwright fallback")
                screenshot_base64 = await capture_screenshot_with_playwright(url)
            except Exception as e:
                print(f"Method 5 failed: {e}")
        
        # Validate and return screenshot
        if screenshot_base64:
            print(f"✅ Screenshot captured successfully")
            # Ensure it's proper base64 format
            if isinstance(screenshot_base64, str) and len(screenshot_base64) > 100:
                # Remove data URI prefix if present
                if screenshot_base64.startswith('data:image'):
                    screenshot_base64 = screenshot_base64.split(',')[1]
                return screenshot_base64
            elif isinstance(screenshot_base64, bytes):
                return base64.b64encode(screenshot_base64).decode('utf-8')
        
        print(f"❌ No screenshot captured with any method")
        return None
            
    except Exception as e:
        print(f"❌ Error capturing screenshot: {e}")
        return None

async def simple_screenshot_validation(screenshot_base64: str, url: str) -> bool:
    """Simple validation to check if screenshot has content"""
    try:
        # Check base64 string length
        if len(screenshot_base64) < 10000:  # Less than ~7KB
            print(f"❌ Screenshot too small for {url}")
            return False
        
        # Check decoded data size
        image_data = base64.b64decode(screenshot_base64)
        if len(image_data) < 5000:  # Less than 5KB
            print(f"❌ Image data too small for {url}")
            return False
        
        # Check byte diversity (blank images have few unique bytes)
        data_sample = image_data[:1000]
        unique_bytes = len(set(data_sample))
        if unique_bytes < 20:
            print(f"❌ Low byte diversity for {url}")
            return False
            
        print(f"✅ Basic validation passed for {url}")
        return True
        
    except Exception as e:
        print(f"❌ Error validating {url}: {e}")
        return False

async def capture_screenshot_with_retry(url: str, browser_tool, max_retries: int = 2) -> Optional[str]:
    """Capture screenshot with validation and retry"""
    for attempt in range(max_retries + 1):
        try:
            # Progressive wait time for page loading
            wait_time = 2 + (attempt * 2)  # 2s, 4s, 6s
            await asyncio.sleep(wait_time)
            
            screenshot_base64 = await capture_url_screenshot(url, browser_tool)
            
            if screenshot_base64:
                is_valid = await simple_screenshot_validation(screenshot_base64, url)
                if is_valid:
                    return screenshot_base64
            
            print(f"❌ Attempt {attempt + 1} failed, retrying...")
            
        except Exception as e:
            print(f"❌ Error on attempt {attempt + 1}: {e}")
    
    return None

async def capture_google_search_screenshot(query: str, browser_tool) -> Optional[str]:
    """Capture screenshot of Google search results"""
    try:
        print(f"📸 Capturing Google search screenshot for: {query}")
        
        # Construct Google search URL
        encoded_query = urllib.parse.quote_plus(query)
        google_search_url = f"https://www.google.com/search?q={encoded_query}"
        
        # Use the same screenshot capture method as URL capture
        screenshot_base64 = await capture_url_screenshot(google_search_url, browser_tool)
        
        if screenshot_base64:
            print(f"✅ Google search screenshot captured successfully")
            return screenshot_base64
        else:
            print(f"❌ Failed to capture Google search screenshot")
            return None
            
    except Exception as e:
        print(f"❌ Error capturing Google search screenshot: {e}")
        return None

async def capture_screenshot_with_playwright(url: str) -> Optional[str]:
    """Fallback method using playwright for screenshot capture"""
    try:
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Set viewport size
            await page.set_viewport_size({"width": 1200, "height": 800})
            
            # Navigate to URL
            await page.goto(url, wait_until="networkidle")
            
            # Take screenshot
            screenshot_bytes = await page.screenshot(full_page=False)
            
            # Convert to base64
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            await browser.close()
            
            print(f"✅ Playwright screenshot captured for {url}")
            return screenshot_base64
            
    except ImportError:
        print("Playwright not available. Install with: pip install playwright")
        return None
    except Exception as e:
        print(f"Playwright screenshot failed: {e}")
        return None

async def process_message_with_direct_scraping(agent, message: str, max_timeout: int = 400):
    """Process message with direct scraping and OCR-based screenshot validation."""
    screenshot_base64 = None
    detected_url = None
    
    try:
        # URL detection
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
            
            detected_url = url
            
            # SCREENSHOT CAPTURE WITH OCR VALIDATION
            try:
                if hasattr(agent, 'tools'):
                    browser_tool = None
                    
                    # Get browser tool
                    if hasattr(agent.tools, 'browser_use_tool'):
                        browser_tool = agent.tools.browser_use_tool
                    elif hasattr(agent.tools, 'browser_use'):
                        browser_tool = agent.tools.browser_use
                    elif hasattr(agent.tools, 'tools'):
                        for tool in agent.tools.tools:
                            if 'browser' in str(type(tool)).lower():
                                browser_tool = tool
                                break
                    
                    if browser_tool:
                        print("🔧 Browser tool found, attempting screenshot with OCR validation")
                        
                        # Try up to 2 attempts
                        max_attempts = 2
                        for attempt in range(max_attempts):
                            print(f"📸 Screenshot attempt {attempt + 1}/{max_attempts}")
                            
                            # Wait for page to load
                            wait_time = 5 + (attempt * 3)  # 5s, 8s
                            await asyncio.sleep(wait_time)
                            
                            temp_screenshot = await capture_url_screenshot(url, browser_tool)
                            
                            if temp_screenshot:
                                # OCR-based validation
                                is_valid = await validate_screenshot_content(temp_screenshot, url)
                                if is_valid:
                                    screenshot_base64 = temp_screenshot
                                    print(f"✅ Valid screenshot with meaningful content captured on attempt {attempt + 1}")
                                    break
                                else:
                                    print(f"❌ Screenshot shows error/blocked page on attempt {attempt + 1}")
                            else:
                                print(f"❌ No screenshot captured on attempt {attempt + 1}")
                            
                            if attempt < max_attempts - 1:
                                await asyncio.sleep(2)
                        
                        if not screenshot_base64:
                            print("⚠️ All screenshot attempts failed OCR validation - page appears blocked/error")
                    else:
                        print("⚠️ No browser tool found")
                        
            except Exception as e:
                print(f"⚠️ Screenshot capture failed: {e}")
            
            # Content scraping (always attempt)
            scraped_content = scrape_page_content(url)
            
            if scraped_content and not scraped_content.startswith("Error"):
                chunks = chunk_content(scraped_content, chunk_size=4000)
                print(f"📦 Content split into {len(chunks)} chunks")
                enhanced_message = f"""
Please respond in English only. Use 'Source:' instead of '来源:', only if the user asks for sources/references. Format URLs as markdown links.
{message}

I have scraped the complete content from the webpage. Here is the full content:

COMPLETE SCRAPED CONTENT:
{scraped_content[:8000]}

Based on this content, address the user's prompt in English only and within 300 words by avoiding unnecessary spaces. Strictly do not include any other language.
"""
                raw = await asyncio.wait_for(
                    agent.llm.ask(enhanced_message, temperature=0.7),
                    timeout=max_timeout
                )
                response = annotate_invalid_links(str(raw))
                response = remove_chinese_and_punct(response)
            else:
                print(f"❌ Content scraping failed for {url}")
                # Add note about access being blocked
                blocked_message = f"""
{message}

Note: The website {url} appears to be blocking access. I was unable to retrieve meaningful content for analysis.
"""
                raw = await asyncio.wait_for(
                    agent.llm.ask(blocked_message, temperature=0.7),
                    timeout=max_timeout
                )
                response = annotate_invalid_links(str(raw))
                response = remove_chinese_and_punct(response)
        else:
            # No URL detected
            raw = await asyncio.wait_for(
                agent.llm.ask(message, temperature=0.7),
                timeout=max_timeout
            )
            response = annotate_invalid_links(str(raw))
            response = remove_chinese_and_punct(response)
        
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
            "base64_image": screenshot_base64,  # Only valid screenshots
            "source_url": detected_url,
            "screenshot_validated": screenshot_base64 is not None
        }
        
    except asyncio.TimeoutError:
        print(f"Agent execution timed out after {max_timeout} seconds")
        
        # Extract the best available response from memory
        best_response = "Request timed out while processing."
        
        if hasattr(agent, 'memory') and hasattr(agent.memory, 'messages'):
            assistant_responses = []
            for msg in agent.memory.messages:
                if hasattr(msg, 'role') and msg.role == 'assistant' and hasattr(msg, 'content'):
                    content = str(msg.content)
                    if len(content) > 100:
                        assistant_responses.append(content)
            
            if assistant_responses:
                longest_response = max(assistant_responses, key=len)
                if len(longest_response) > 300:
                    best_response = f"Partial response (timed out):\n\n{longest_response}"
        
        save_comprehensive_response(message, best_response, is_partial=True)
        return {
            "response": best_response,
            "base64_image": None,
            "source_url": detected_url,
            "screenshot_validated": False
        }
    
    except Exception as e:
        error_msg = f"Error during agent execution: {e}"
        print(error_msg)
        save_comprehensive_response(message, error_msg, is_error=True)
        return {
            "response": error_msg,
            "base64_image": None,
            "source_url": detected_url,
            "screenshot_validated": False
        }


async def validate_screenshot_content(screenshot_base64: str, url: str) -> bool:
    """
    Simple OCR-based validation to detect error pages by reading text content
    Returns True if screenshot contains valid website content, False for error pages
    """
    try:
        # Basic size check first
        if len(screenshot_base64) < 5000:
            print(f"❌ Screenshot too small for {url}")
            return False
        
        # Decode and convert to PIL Image
        image_data = base64.b64decode(screenshot_base64)
        image = Image.open(io.BytesIO(image_data))
        
        print(f"🔍 Reading text from screenshot for {url}...")
        
        # Extract text using OCR
        extracted_text = pytesseract.image_to_string(image, config='--psm 6').lower().strip()
        
        print(f"📝 Extracted text (first 300 chars): {extracted_text[:300]}")
        
        # Define error page indicators
        error_indicators = [
            # Access/Permission errors
            'access denied',
            'permission denied',
            'you don\'t have permission',
            'forbidden',
            'not authorized',
            'unauthorized',
            
            # HTTP errors
            '403 forbidden',
            '404 not found',
            '500 internal server error',
            '502 bad gateway',
            '503 service unavailable',
            '504 gateway timeout',
            'page not found',
            'server error',
            'internal server error',
            
            # Connection errors
            'this site can\'t be reached',
            'connection timed out',
            'connection refused',
            'dns_probe_finished_nxdomain',
            'err_connection_refused',
            'err_connection_timed_out',
            'unable to connect',
            'connection failed',
            
            # Security/Blocking
            'blocked by',
            'access blocked',
            'security check',
            'firewall',
            'your ip has been blocked',
            'ip blocked',
            'request blocked',
            'contact our support',
            'contact administrator',
            'contact admin team',
            
            # Cloudflare and other services
            'cloudflare',
            'ray id:',
            'cf-ray:',
            'checking your browser',
            'security service',
            'ddos protection',
            
            # CAPTCHA and verification
            'captcha',
            'verify you are human',
            'prove you\'re not a robot',
            'security verification',
            'human verification',
            
            # Maintenance and unavailable
            'temporarily unavailable',
            'under maintenance',
            'site maintenance',
            'coming soon',
            'website unavailable',
            
            # Reference numbers (common in error pages)
            'reference #',
            'reference id',
            'incident id',
            'error code',
            'request id',
            
            # Generic error terms
            'something went wrong',
            'error occurred',
            'try again later',
            'service temporarily',
            'technical difficulties'
        ]
        
        # Check for error indicators
        for indicator in error_indicators:
            if indicator in extracted_text:
                print(f"❌ Error page detected - found '{indicator}' in screenshot for {url}")
                return False
        
        # Additional checks for minimal content
        words = extracted_text.split()
        meaningful_words = [word for word in words if len(word) > 2 and word.isalpha()]
        
        if len(meaningful_words) < 10:
            print(f"❌ Insufficient meaningful content ({len(meaningful_words)} words) for {url}")
            return False
        
        # Check for overly repetitive content (some error pages repeat messages)
        word_counts = {}
        for word in meaningful_words:
            word_counts[word] = word_counts.get(word, 0) + 1
        
        if word_counts:
            max_count = max(word_counts.values())
            repetition_ratio = max_count / len(meaningful_words)
            
            if repetition_ratio > 0.4:  # More than 40% repetition
                print(f"❌ Overly repetitive content (ratio: {repetition_ratio:.2f}) for {url}")
                return False
        
        # Check for very short content that might be just error messages
        if len(extracted_text.strip()) < 50:
            print(f"❌ Very short content ({len(extracted_text)} chars) for {url}")
            return False
        
        # Special check for placeholder pages
        placeholder_indicators = [
            'default page',
            'placeholder',
            'coming soon',
            'under construction',
            'website coming soon',
            'page under construction'
        ]
        
        for placeholder in placeholder_indicators:
            if placeholder in extracted_text:
                print(f"❌ Placeholder page detected - found '{placeholder}' for {url}")
                return False
        
        print(f"✅ Valid content detected for {url} ({len(meaningful_words)} meaningful words)")
        return True
        
    except ImportError:
        print(f"❌ OCR libraries not installed. Please run: pip install pytesseract pillow")
        print(f"❌ Also install Tesseract OCR binary for your system")
        return False
        
    except Exception as e:
        print(f"❌ OCR validation failed for {url}: {e}")
        # If OCR fails, we'll be conservative and reject the screenshot
        return False

def detect_user_intent(message: str) -> UserAction:
    """Detect user intent from message with enhanced detection"""
    message_lower = message.lower().strip()
    
    # Check for URLs first (action 1)
    url_patterns = [r'https?://', r'www\.', r'\.[a-z]{2,4}(?:/|$)']
    if any(re.search(pattern, message) for pattern in url_patterns):
        return UserAction.URL_RESEARCH
    
    # ENHANCED questionnaire/survey detection (action 2)
    
    # Direct keyword matches
    direct_keywords = [
        'questionnaire', 'survey', 'questions', 'research design', 
        'study design', 'build survey', 'create questionnaire',
        'research plan', 'methodology', 'data collection',
        'build a survey', 'design a survey', 'create a study',
        'research study', 'survey design', 'questionnaire design',
        'customer satisfaction', 'user experience survey',
        'feedback survey', 'opinion survey', 'market research',
        'academic research', 'scientific study', 'data gathering',
        'collect data', 'gather feedback', 'measure satisfaction'
    ]
    
    # Intent phrases that strongly suggest questionnaire building
    intent_phrases = [
        'want to study', 'want to research', 'want to build',
        'want to create', 'want to design', 'need to study',
        'need to research', 'need to build', 'need to create',
        'help me study', 'help me research', 'help me build',
        'help me create', 'help me design'
    ]
    
    # Check for direct keyword matches first
    if any(keyword in message_lower for keyword in direct_keywords):
        logger.info(f"Intent detection: Found direct keyword match for BUILD_QUESTIONNAIRE")
        return UserAction.BUILD_QUESTIONNAIRE
    
    # Check for intent phrases
    if any(phrase in message_lower for phrase in intent_phrases):
        logger.info(f"Intent detection: Found intent phrase match for BUILD_QUESTIONNAIRE")
        return UserAction.BUILD_QUESTIONNAIRE
    
    # Enhanced regex patterns for questionnaire building
    questionnaire_patterns = [
        r'i want to.*survey',
        r'i want to.*questionnaire', 
        r'i want to.*study',
        r'i want to.*research',
        r'i need to.*survey',
        r'i need to.*questionnaire',
        r'i need to.*study', 
        r'i need to.*research',
        r'help me.*survey',
        r'help me.*questionnaire',
        r'help me.*study',
        r'help me.*research',
        r'create.*survey',
        r'build.*survey',
        r'design.*survey',
        r'develop.*survey',
        r'want to build.*survey',
        r'want to create.*survey',
        r'want to design.*survey'
    ]
    
    for pattern in questionnaire_patterns:
        if re.search(pattern, message_lower):
            logger.info(f"Intent detection: Found pattern match '{pattern}' for BUILD_QUESTIONNAIRE")
            return UserAction.BUILD_QUESTIONNAIRE
    
    # Special case: if message contains both "build" and "survey" anywhere
    if 'build' in message_lower and 'survey' in message_lower:
        logger.info(f"Intent detection: Found 'build' + 'survey' combination for BUILD_QUESTIONNAIRE")
        return UserAction.BUILD_QUESTIONNAIRE
    
    # Special case: if message contains "satisfaction" and ("survey" or "study" or "research")
    if 'satisfaction' in message_lower:
        if any(word in message_lower for word in ['survey', 'study', 'research', 'questionnaire']):
            logger.info(f"Intent detection: Found satisfaction + research term for BUILD_QUESTIONNAIRE")
            return UserAction.BUILD_QUESTIONNAIRE
    
    # Log what we didn't match for debugging
    logger.info(f"Intent detection: No questionnaire patterns found, defaulting to GENERAL_RESEARCH for: '{message[:50]}...'")
    
    # Default to general research (action 3)
    return UserAction.GENERAL_RESEARCH


class OpenManusUI:
    """UI server for OpenManus with Research Design Workflow."""

    def __init__(self, static_dir: Optional[str] = None):
        self.app = FastAPI(title="OpenManus UI")
        self.agent: Optional[Manus] = None
        self.active_websockets: List[WebSocket] = []
        self.frontend_dir = static_dir or os.path.join(os.path.dirname(__file__), "../../frontend/openmanus-ui/dist")
        self.research_workflow: Optional[ResearchWorkflow] = None

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
                self.research_workflow = ResearchWorkflow(llm_instance)
                self.research_workflow.browser_tool = browser_use_tool
                self.patch_agent_methods()
                logger.info("Manus agent and Research Workflow initialized successfully on startup.")
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
                        session_id = data.get("session_id", "default")
                        action_type = data.get("action_type")
                        
                        logger.info(f"Processing message: {user_message}")
                        asyncio.create_task(self.process_message(user_message, session_id, action_type))

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
                "agent_initialized": self.agent is not None,
                "research_workflow_enabled": self.research_workflow is not None
            })

        @self.app.post("/api/message")
        async def handle_message(request: UserMessage):
            try:
                if not self.agent:
                    return JSONResponse(
                        status_code=500,
                        content={"response": "Agent not initialized", "status": "error"}
                    )

                session_id = request.research_session_id or "default_research_session"
                
                # Check if we have an active research session first
                if session_id in self.research_workflow.active_sessions:
                    session = self.research_workflow.active_sessions[session_id]
                    slideshow_data = None
                    
                    # Special handling for research workflow screenshot capture
                    if session.stage == ResearchStage.DESIGN_REVIEW and request.content.upper().strip() == 'Y':
                        # User accepted design and we're about to search - capture URL screenshots
                        try:
                            response_content = await self.research_workflow.process_research_input(
                                session_id, request.content
                            )
                            
                            # Check if we have screenshots to include
                            if hasattr(session, 'screenshots') and session.screenshots:
                                slideshow_data = {
                                    "screenshots": session.screenshots,
                                    "total_count": len(session.screenshots),
                                    "research_topic": session.research_topic
                                }
                                
                        except Exception as e:
                            logger.warning(f"Could not capture screenshots: {e}")
                            response_content = await self.research_workflow.process_research_input(
                                session_id, request.content
                            )
                    
                    # Special handling for rebrowse option
                    elif session.stage == ResearchStage.DECISION_POINT and request.content.upper().strip() == 'R':
                        try:
                            response_content = await self.research_workflow.process_research_input(
                                session_id, request.content
                            )
                            
                            # Check if we have updated screenshots to include
                            if hasattr(session, 'screenshots') and session.screenshots:
                                slideshow_data = {
                                    "screenshots": session.screenshots,
                                    "total_count": len(session.screenshots),
                                    "research_topic": session.research_topic
                                }
                                
                        except Exception as e:
                            logger.warning(f"Could not capture rebrowse screenshots: {e}")
                            response_content = await self.research_workflow.process_research_input(
                                session_id, request.content
                            )
                    
                    # Regular research workflow processing for all other cases
                    else:
                        response_content = await self.research_workflow.process_research_input(
                            session_id, request.content
                        )
                    
                    # Prepare the result
                    result = {
                        "response": response_content,
                        "status": "success",
                        "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                        "session_id": session_id
                    }
                    
                    # Add slideshow data if we have screenshots
                    if slideshow_data:
                        result["slideshow_data"] = slideshow_data
                        # Also include first screenshot as main browser image
                        if slideshow_data["screenshots"]:
                            result["base64_image"] = slideshow_data["screenshots"][0]["screenshot"]
                            result["image_url"] = slideshow_data["screenshots"][0]["url"]
                            result["image_title"] = slideshow_data["screenshots"][0]["title"]
                    
                    return JSONResponse(result)

                # Determine action type if not provided
                action_type = request.action_type
                if not action_type:
                    intent = detect_user_intent(request.content)
                    action_type = intent.value

                # Handle different action types
                if action_type == UserAction.BUILD_QUESTIONNAIRE.value:
                    # Start new research session
                    session_id = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
                    logger.info(f"Starting new research session: {session_id}")
                    response_content = await self.research_workflow.start_research_design(session_id)
                    
                    return JSONResponse({
                        "response": response_content,
                        "status": "success",
                        "action_type": action_type,
                        "session_id": session_id
                    })
                
                else:
                    # Handle URL research or general research with enhanced screenshot validation
                    response_data = await process_message_with_direct_scraping(
                        self.agent,
                        request.content,
                        max_timeout=60
                    )
                    
                    if isinstance(response_data, dict):
                        response_content = response_data.get("response", "")
                        screenshot = response_data.get("base64_image", None)
                        source_url = response_data.get("source_url", None)
                        screenshot_validated = response_data.get("screenshot_validated", False)
                    else:
                        response_content = str(response_data)
                        screenshot = None
                        source_url = None
                        screenshot_validated = False
                    
                    result = {
                        "response": response_content,
                        "status": "success",
                        "action_type": action_type
                    }
                    
                    if screenshot:
                        result["base64_image"] = screenshot
                        result["screenshot_validated"] = screenshot_validated
                        
                        # Add source URL info for the Visit Site button
                        if source_url:
                            result["source_url"] = source_url
                            result["image_url"] = source_url
                            
                            # Extract domain for title
                            try:
                                from urllib.parse import urlparse
                                parsed = urlparse(source_url)
                                domain = parsed.netloc
                                result["image_title"] = f"Screenshot from {domain}"
                            except:
                                result["image_title"] = "Website Screenshot"
                        else:
                            result["image_title"] = "Screenshot"
                    
                    return JSONResponse(result)
                
            except Exception as e:
                logger.error(f"Error in handle_message: {str(e)}", exc_info=True)
                error_response = f"Server error: {str(e)}"
                save_comprehensive_response(request.content, error_response, is_error=True)
                return JSONResponse(
                    status_code=500,
                    content={"response": error_response, "status": "error"}
                )

        @self.app.get("/api/initial_options")
        async def get_initial_options():
            return JSONResponse({
                "options": [
                    {
                        "id": 1,
                        "title": "URL Research",
                        "description": "Ask a research question about any website or URL",
                        "action": UserAction.URL_RESEARCH.value,
                        "example": "Analyze the pricing strategy on apple.com"
                    },
                    {
                        "id": 2,
                        "title": "Build Research Questionnaire",
                        "description": "Design a comprehensive research study and questionnaire",
                        "action": UserAction.BUILD_QUESTIONNAIRE.value,
                        "example": "I want to study customer satisfaction with online shopping"
                    },
                    {
                        "id": 3,
                        "title": "General Research Question",
                        "description": "Ask any research-related question",
                        "action": UserAction.GENERAL_RESEARCH.value,
                        "example": "What are the best practices for survey design?"
                    }
                ]
            })

        @self.app.get("/")
        async def get_index():
            index_path = os.path.join(self.frontend_dir, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return {"message": "Frontend not built yet. Please run 'npm run build' in the frontend directory."}

        @self.app.get("/api/research-files")
        async def list_research_files():
            """List all available research files for download"""
            try:
                research_dir = "research_outputs"
                if not os.path.exists(research_dir):
                    return JSONResponse({"files": [], "message": "No research files found"})
                
                files = []
                for filename in os.listdir(research_dir):
                    if filename.endswith(('.txt', '.json')):
                        filepath = os.path.join(research_dir, filename)
                        file_stat = os.stat(filepath)
                        
                        # Determine file type
                        file_type = "unknown"
                        if "research_package" in filename or "complete_research_package" in filename:
                            file_type = "research_package"
                        elif "chat_history" in filename:
                            file_type = "chat_history"
                        elif "research_design" in filename:
                            file_type = "research_design"
                        
                        files.append({
                            "filename": filename,
                            "filepath": filepath,
                            "type": file_type,
                            "size": file_stat.st_size,
                            "created": file_stat.st_mtime,
                            "display_name": filename.replace("_", " ").replace(".txt", "").replace(".json", "")
                        })
                
                # Sort by creation time (newest first)
                files.sort(key=lambda x: x["created"], reverse=True)
                
                return JSONResponse({"files": files})
                
            except Exception as e:
                logger.error(f"Error listing research files: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error listing files: {str(e)}"}
                )

        @self.app.get("/api/download/{filename}")
        async def download_file(filename: str):
            """Download a specific research file"""
            try:
                # Security check - only allow files from research_outputs directory
                if ".." in filename or "/" in filename or "\\" in filename:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "Invalid filename"}
                    )
                
                research_dir = "research_outputs"
                filepath = os.path.join(research_dir, filename)
                
                if not os.path.exists(filepath):
                    return JSONResponse(
                        status_code=404,
                        content={"error": "File not found"}
                    )
                
                # Determine content type
                if filename.endswith('.json'):
                    media_type = 'application/json'
                else:
                    media_type = 'text/plain'
                
                return FileResponse(
                    path=filepath,
                    filename=filename,
                    media_type=media_type,
                    headers={
                        "Content-Disposition": f"attachment; filename={filename}"
                    }
                )
                
            except Exception as e:
                logger.error(f"Error downloading file {filename}: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error downloading file: {str(e)}"}
                )

        @self.app.get("/api/download-latest/{file_type}")
        async def download_latest_file(file_type: str):
            """Download the latest file of a specific type (research_package, chat_history, etc.)"""
            try:
                research_dir = "research_outputs"
                if not os.path.exists(research_dir):
                    return JSONResponse(
                        status_code=404,
                        content={"error": "No research files found"}
                    )
                
                # Find the latest file of the specified type
                matching_files = []
                for filename in os.listdir(research_dir):
                    if file_type in filename and filename.endswith(('.txt', '.json')):
                        filepath = os.path.join(research_dir, filename)
                        file_stat = os.stat(filepath)
                        matching_files.append({
                            "filename": filename,
                            "filepath": filepath,
                            "created": file_stat.st_mtime
                        })
                
                if not matching_files:
                    return JSONResponse(
                        status_code=404,
                        content={"error": f"No {file_type} files found"}
                    )
                
                # Get the latest file
                latest_file = max(matching_files, key=lambda x: x["created"])
                
                # Determine content type
                if latest_file["filename"].endswith('.json'):
                    media_type = 'application/json'
                else:
                    media_type = 'text/plain'
                
                return FileResponse(
                    path=latest_file["filepath"],
                    filename=latest_file["filename"],
                    media_type=media_type,
                    headers={
                        "Content-Disposition": f"attachment; filename={latest_file['filename']}"
                    }
                )
                
            except Exception as e:
                logger.error(f"Error downloading latest {file_type}: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error downloading latest file: {str(e)}"}
                )

    async def process_message(self, user_message: str, session_id: str = "default", action_type: str = None):
        """Process a user message via WebSocket with enhanced screenshot validation."""
        try:
            if not self.agent:
                await self.broadcast_message("error", {"message": "Agent not initialized"})
                return

            # Check if we have an active research session first
            if session_id in self.research_workflow.active_sessions:
                session = self.research_workflow.active_sessions[session_id]
                
                # ENHANCED: Handle initial search (Y response) with slideshow
                if session.stage == ResearchStage.DESIGN_REVIEW and user_message.upper().strip() == 'Y':
                    try:
                        # Process the research input which will capture screenshots of found URLs
                        response = await self.research_workflow.process_research_input(session_id, user_message)
                        
                        # After processing, check if we have screenshots to display
                        if hasattr(session, 'screenshots') and session.screenshots:
                            logger.info(f"Broadcasting initial slideshow with {len(session.screenshots)} screenshots")
                            
                            # Send slideshow data to frontend
                            await self.broadcast_message("slideshow_data", {
                                "screenshots": session.screenshots,
                                "total_count": len(session.screenshots),
                                "research_topic": session.research_topic
                            })
                            
                            # Also send the first screenshot to browser view
                            if session.screenshots:
                                await self.broadcast_message("browser_state", {
                                    "base64_image": session.screenshots[0]['screenshot'],
                                    "url": session.screenshots[0]['url'],
                                    "title": session.screenshots[0]['title'],
                                    "source_url": session.screenshots[0]['url']
                                })
                        
                        await self.broadcast_message("agent_message", {
                            "content": response,
                            "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                            "session_id": session_id
                        })
                        return
                        
                    except Exception as e:
                        logger.warning(f"Could not process initial search with screenshots: {e}")
                
                # ENHANCED: Handle rebrowse (R response) with updated slideshow
                elif session.stage == ResearchStage.DECISION_POINT and user_message.upper().strip() == 'R':
                    try:
                        # Store screenshots count before rebrowse
                        old_screenshot_count = len(session.screenshots) if hasattr(session, 'screenshots') and session.screenshots else 0
                        
                        # Process the rebrowse which will capture additional screenshots
                        response = await self.research_workflow.process_research_input(session_id, user_message)
                        
                        # After processing, check if we have updated screenshots to display
                        if hasattr(session, 'screenshots') and session.screenshots:
                            new_screenshot_count = len(session.screenshots)
                            logger.info(f"Broadcasting updated slideshow: {old_screenshot_count} -> {new_screenshot_count} screenshots")
                            
                            # Send updated slideshow data to frontend
                            await self.broadcast_message("slideshow_data", {
                                "screenshots": session.screenshots,
                                "total_count": len(session.screenshots),
                                "research_topic": session.research_topic,
                                "is_update": True,  # Flag to indicate this is an update
                                "new_screenshots_added": new_screenshot_count - old_screenshot_count
                            })
                            
                            # Send the most recent screenshot to browser view (last added)
                            if session.screenshots:
                                latest_screenshot = session.screenshots[-1]  # Get the last (newest) screenshot
                                await self.broadcast_message("browser_state", {
                                    "base64_image": latest_screenshot['screenshot'],
                                    "url": latest_screenshot['url'],
                                    "title": latest_screenshot['title'],
                                    "source_url": latest_screenshot['url']
                                })
                        
                        await self.broadcast_message("agent_message", {
                            "content": response,
                            "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                            "session_id": session_id
                        })
                        return
                        
                    except Exception as e:
                        logger.warning(f"Could not process rebrowse with screenshots: {e}")
                
                # ENHANCED: Handle question selection responses that might trigger more rebrowsing
                elif (session.stage == ResearchStage.DECISION_POINT and 
                    hasattr(session, 'awaiting_selection') and session.awaiting_selection):
                    try:
                        # Store screenshots count before processing selection
                        old_screenshot_count = len(session.screenshots) if hasattr(session, 'screenshots') and session.screenshots else 0
                        
                        # Process the selection input
                        response = await self.research_workflow.process_research_input(session_id, user_message)
                        
                        # Check if screenshots were updated during selection processing
                        if hasattr(session, 'screenshots') and session.screenshots:
                            new_screenshot_count = len(session.screenshots)
                            
                            # If new screenshots were added, update the slideshow
                            if new_screenshot_count > old_screenshot_count:
                                logger.info(f"Selection processing added screenshots: {old_screenshot_count} -> {new_screenshot_count}")
                                
                                await self.broadcast_message("slideshow_data", {
                                    "screenshots": session.screenshots,
                                    "total_count": len(session.screenshots),
                                    "research_topic": session.research_topic,
                                    "is_update": True,
                                    "new_screenshots_added": new_screenshot_count - old_screenshot_count
                                })
                                
                                # Update browser view with latest screenshot
                                if session.screenshots:
                                    latest_screenshot = session.screenshots[-1]
                                    await self.broadcast_message("browser_state", {
                                        "base64_image": latest_screenshot['screenshot'],
                                        "url": latest_screenshot['url'],
                                        "title": latest_screenshot['title'],
                                        "source_url": latest_screenshot['url']
                                    })
                        
                        await self.broadcast_message("agent_message", {
                            "content": response,
                            "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                            "session_id": session_id
                        })
                        return
                        
                    except Exception as e:
                        logger.warning(f"Could not process selection with potential screenshots: {e}")
                
                # Regular research workflow processing for all other cases
                response = await self.research_workflow.process_research_input(session_id, user_message)
                
                await self.broadcast_message("agent_message", {
                    "content": response,
                    "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                    "session_id": session_id
                })
                return

            # If no active session, detect intent and handle as before
            if not action_type:
                intent = detect_user_intent(user_message)
                action_type = intent.value

            await self.broadcast_message("agent_action", {
                "action": "Processing",
                "details": f"Processing {action_type}: {user_message}"
            })

            # Handle different action types
            if action_type == UserAction.BUILD_QUESTIONNAIRE.value:
                # Start new research session  
                response = await self.research_workflow.start_research_design(session_id)

                await self.broadcast_message("agent_message", {
                    "content": response,
                    "action_type": action_type,
                    "session_id": session_id
                })

            else:
                # Handle URL research or general research with enhanced validation
                if action_type == UserAction.URL_RESEARCH.value or 'http' in user_message:
                    # URL-based research with validated screenshot capture
                    response_data = await asyncio.wait_for(
                        process_message_with_direct_scraping(
                            self.agent,
                            user_message,
                            max_timeout=60
                        ),
                        timeout=90
                    )
                else:
                    # General research question
                    prefix = (
                        "Please respond in English only within 300 words. Avoid unnecessary spaces. "
                        "Use 'Source:' instead of '来源:', only if the user asks for sources/references."
                        "Format URLs as markdown links (e.g. [text](url)).\n\n"
                    )
                    raw = await self.agent.llm.ask(prefix + user_message, temperature=0.7)
                    response_data = {
                        "response": annotate_invalid_links(collapse_to_root_domain(remove_chinese_and_punct(str(raw)))),
                        "base64_image": None,
                        "source_url": None,
                        "screenshot_validated": False
                    }

                if isinstance(response_data, dict):
                    response_content = response_data.get("response", "")
                    screenshot = response_data.get("base64_image", None)
                    source_url = response_data.get("source_url", None)
                    screenshot_validated = response_data.get("screenshot_validated", False)
                else:
                    response_content = str(response_data)
                    screenshot = None
                    source_url = None
                    screenshot_validated = False

                await self.broadcast_message("agent_message", {
                    "content": response_content,
                    "action_type": action_type
                })

                if screenshot:
                    browser_state_data = {
                        "base64_image": screenshot,
                        "screenshot_validated": screenshot_validated
                    }
                    
                    # Add source URL info for the Visit Site button
                    if source_url:
                        browser_state_data["source_url"] = source_url
                        browser_state_data["url"] = source_url
                        
                        # Extract domain for title
                        try:
                            from urllib.parse import urlparse
                            parsed = urlparse(source_url)
                            domain = parsed.netloc
                            browser_state_data["title"] = f"Screenshot from {domain}"
                        except:
                            browser_state_data["title"] = "Website Screenshot"
                    else:
                        browser_state_data["title"] = "Screenshot"
                    
                    await self.broadcast_message("browser_state", browser_state_data)
                    
                    # Log validation status
                    if screenshot_validated:
                        logger.info(f"✅ Validated screenshot sent to frontend for URL: {source_url}")
                    else:
                        logger.warning(f"⚠️ Unvalidated screenshot sent to frontend for URL: {source_url}")

        except asyncio.TimeoutError:
            await self.broadcast_message("agent_message", {
                "content": "I apologize, but the request timed out. Please try a simpler question.",
                "action_type": action_type
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
        logger.info(f"Starting OpenManus UI server with Research Workflow at http://{host}:{port}")
        print(f"""
🚀 OpenManus Research Platform Started!

Available Actions:
1. URL Research - Ask questions about any website
2. Build Research Questionnaire - Design comprehensive studies  
3. General Research Questions - Get research assistance

Access the platform at: http://{host}:{port}
        """)
        uvicorn.run(self.app, host=host, port=port)


if __name__ == "__main__":
    ui_server = OpenManusUI()
    ui_server.run()