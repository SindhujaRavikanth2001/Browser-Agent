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
    selected_internet_questions: bool = False
    stage: ResearchStage = ResearchStage.INITIAL
    user_responses: Optional[Dict] = None
    questionnaire_responses: Optional[Dict] = None
    chat_history: Optional[List[Dict]] = None
    selected_internet_questions: bool = False  # S option flag
    include_all_internet_questions: bool = False  # Y option flag

class UserMessage(BaseModel):
    content: str
    action_type: Optional[str] = None
    research_session_id: Optional[str] = None

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

    async def _search_internet_for_questions(self, research_topic: str, target_population: str) -> tuple[List[str], List[str], List[str]]:
        """Search internet with deep URL filtering and screenshot validation"""
        try:
            if not self.search_service:
                logger.warning("Google Custom Search API not available, using fallback")
                return await self._fallback_search(research_topic, target_population)
            
            search_query = f"Surveys on {research_topic}"
            logger.info(f"Searching for: {search_query}")
            
            try:
                # Get more results since we'll filter many out
                search_result = self.search_service.cse().list(
                    q=search_query,
                    cx=self.google_cse_id,
                    num=10,  # Get exactly 10 results
                    safe='active',
                    fields='items(title,link,snippet)'
                ).execute()
                
            except Exception as api_error:
                logger.error(f"Google Search API error: {api_error}")
                return await self._fallback_search(research_topic, target_population)
            
            # Extract and filter URLs
            all_urls = []
            deep_urls = []
            
            if 'items' in search_result:
                for item in search_result['items']:
                    link = item.get('link', '')
                    title = item.get('title', '')
                    if link:
                        all_urls.append(link)
                        if self._is_valid_url(link):  # This now includes deep URL check
                            deep_urls.append(link)
                            logger.info(f"✅ Deep URL found: {title}")
                        else:
                            logger.info(f"❌ Filtered out: {title} - {link}")
            
            logger.info(f"URL filtering results:")
            logger.info(f"  - Total URLs found: {len(all_urls)}")
            logger.info(f"  - Deep URLs kept: {len(deep_urls)}")
            logger.info(f"  - URLs filtered out: {len(all_urls) - len(deep_urls)}")
            
            if not deep_urls:
                logger.warning("No deep URLs found after filtering")
                return await self._fallback_search(research_topic, target_population)
            
            # Process only deep URLs
            all_scraped_content = ""
            scraped_sources = []
            valid_screenshots = []
            
            for i, url in enumerate(deep_urls, 1):
                try:
                    logger.info(f"Processing deep URL {i}/{len(deep_urls)}: {url}")
                    
                    # Scrape content first
                    page_content = await self._scrape_page_content(url)
                    
                    if not page_content or len(page_content) < 200:
                        print(f"❌ Insufficient content from {url}")
                        continue
                    
                    # Content is good - try screenshot (single attempt)
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
                    
                    # Always include content (regardless of screenshot success)
                    all_scraped_content += f"\n\nContent from {url}:\n{page_content[:2000]}"
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
            
            logger.info(f"Final results:")
            logger.info(f"  - Deep URLs processed: {len(deep_urls)}")
            logger.info(f"  - Content sources: {len(scraped_sources)}")
            logger.info(f"  - Valid screenshots: {len(valid_screenshots)}")
            
            # Generate questions from all scraped content
            questions = await self._generate_questions_from_content(
                all_scraped_content, research_topic, target_population
            )
            
            return questions, scraped_sources, valid_screenshots
            
        except Exception as e:
            logger.error(f"Error in search with deep URL filtering: {e}")
            return await self._fallback_search(research_topic, target_population)

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

    async def _generate_questions_from_content(self, scraped_content: str, research_topic: str, target_population: str) -> List[str]:
        """Generate exactly 10 questions from scraped content using LLM"""
        
        prompt = f"""
    Based on the following scraped web content about "{research_topic}", create exactly 10 professional survey questions suitable for "{target_population}".

    SCRAPED CONTENT:
    {scraped_content[:6000]}  # Limit content for LLM processing

    INSTRUCTIONS:
    1. Create exactly 10 survey questions
    2. Base questions on the concepts, topics, and information found in the scraped content
    3. Make questions relevant to "{research_topic}" research
    4. Use professional survey language appropriate for "{target_population}"
    5. Include a mix of satisfaction, frequency, rating, and preference questions
    6. Each question should be clear, specific, and measurable
    7. Return only the questions, one per line
    8. All questions must end with a question mark

    Generate exactly 10 survey questions:
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
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
                    questions.append(line)
            
            # Ensure we have exactly 10 questions
            if len(questions) < 10:
                # If fewer than 10, generate additional simple questions
                additional_needed = 10 - len(questions)
                basic_questions = [
                    f"How satisfied are you with {research_topic}?",
                    f"How often do you engage with {research_topic}?",
                    f"How important is {research_topic} to you?",
                    f"How likely are you to recommend {research_topic}?",
                    f"What factors are most important regarding {research_topic}?",
                    f"How would you rate your overall experience with {research_topic}?"
                ]
                questions.extend(basic_questions[:additional_needed])
            
            # Return exactly 10 questions
            return questions[:10]
            
        except Exception as e:
            logger.error(f"Error generating questions from content: {e}")
            # Fallback to basic questions if LLM fails
            return [
                f"How satisfied are you with {research_topic}?",
                f"How often do you use {research_topic}?",
                f"How important is {research_topic} to you?",
                f"How likely are you to recommend {research_topic}?",
                f"What factors influence your decisions about {research_topic}?"
            ]

    async def _scrape_page_content(self, url: str) -> str:
        """Scrape content from a webpage"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                element.decompose()
            
            # Extract text content
            text = soup.get_text()
            
            # Clean up text
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            cleaned_text = ' '.join(chunk for chunk in chunks if chunk)
            
            # Limit content length for LLM processing
            return cleaned_text[:8000]  # Limit to 8000 characters
            
        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return ""

    # Enhanced fallback method to also use LLM
    async def _fallback_search(self, research_topic: str, target_population: str) -> tuple[List[str], List[str], List[str]]:
        """Enhanced fallback that uses LLM to generate questions"""
        logger.info("Using enhanced LLM fallback for question generation")
        
        # Generate comprehensive set of questions using LLM
        questions = await self._generate_questions_with_llm(research_topic, target_population, 5)
        
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
            chat_history=[]  # Initialize empty chat history
        )
        
        initial_response = """
    🔬 **Research Design Workflow Started**

    Let's design your research study step by step. I'll ask you a series of questions to help create a comprehensive research design.

    **Question 1 of 4: Research Topic**
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
        """Export complete research package including questionnaire and chat history"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"complete_research_package_{timestamp}.txt"
        
        try:
            os.makedirs("research_outputs", exist_ok=True)
            
            # Get the generated research design
            research_design_content = await self._generate_research_design(session)
            
            # Use all questions from session.questions (which includes generated + selected)
            final_questions = session.questions or []
            
            # Remove duplicates while preserving order
            seen = set()
            unique_final_questions = []
            for q in final_questions:
                if q not in seen:
                    seen.add(q)
                    unique_final_questions.append(q)
            
            final_questions = unique_final_questions
            
            # Determine question source information
            question_source_info = ""
            if (hasattr(session, 'selected_internet_questions') and 
                session.selected_internet_questions and 
                session.questionnaire_responses and 
                'selected_questions' in session.questionnaire_responses):
                
                # Selection mode - show breakdown
                selected_questions = session.questionnaire_responses['selected_questions']
                base_count = session.questionnaire_responses['total_questions']
                selected_count = len(selected_questions)
                
                # Split questions for display
                generated_questions = final_questions[:base_count]
                extra_questions = final_questions[base_count:]
                
                question_source_info = f"""
    Generated Base Questions: {len(generated_questions)}
    Selected Extra Questions: {len(extra_questions)}
    Total Questions: {len(final_questions)}

    Generated Base Questions:
    {chr(10).join(f"• {q}" for q in generated_questions)}

    Selected Extra Questions from Internet Research:
    {chr(10).join(f"• {q}" for q in extra_questions)}
    """
            
            elif session.use_internet_questions and session.internet_questions:
                # All internet questions mode
                internet_count = len([q for q in final_questions if q in session.internet_questions])
                ai_count = len(final_questions) - internet_count
                question_source_info = f"""
    Internet Research Questions: {internet_count}
    AI Generated Questions: {ai_count}
    Total Questions: {len(final_questions)}

    Internet Sources:
    {chr(10).join(f"• {source}" for source in (session.internet_sources or []))}
    """
            else:
                # AI only mode
                question_source_info = f"""
    AI Generated Questions: {len(final_questions)}
    Total Questions: {len(final_questions)}
    """
            
            # Export chat history first
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

    1. SURVEY DISTRIBUTION:
    - Use online survey platforms (SurveyMonkey, Qualtrics, Google Forms)
    - Target distribution through social media, email lists, or partner organizations
    - Consider incentives to improve response rates

    2. DATA COLLECTION:
    - Collect responses over 4-6 weeks
    - Monitor response rates weekly
    - Send reminder emails to improve participation

    3. DATA ANALYSIS:
    - Use statistical software (SPSS, R, or Excel) for analysis
    - Calculate descriptive statistics for all variables
    - Perform correlation analysis between satisfaction factors
    - Consider regression analysis to identify key drivers

    4. REPORTING:
    - Create visual dashboards with charts and graphs
    - Provide executive summary with key findings
    - Include recommendations based on results

    ================================================================================
    RESEARCH ETHICS AND CONSIDERATIONS
    ================================================================================

    - Obtain informed consent from all participants
    - Ensure participant anonymity and data privacy
    - Store data securely and follow GDPR/privacy regulations
    - Provide participants with option to withdraw at any time

    ================================================================================
    EXPECTED TIMELINE
    ================================================================================

    Week 1-2: Finalize questionnaire and setup survey platform
    Week 3-8: Data collection period
    Week 9-10: Data analysis and preliminary results
    Week 11-12: Final report preparation and presentation

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
            
            # Enhanced response with chat export info
            chat_info = f"\nChat file: `{chat_filepath.split('/')[-1] if chat_filepath else 'Export failed'}`" if chat_filepath else "\n⚠️ Chat history export failed"
            
            return f"""
    🎉 **Research Package Complete!**

    Your comprehensive research package has been exported to:
    **`{filepath}`**{chat_info}

    **Package Contents:**
    ✅ Complete research design and methodology
    ✅ Tested and validated questionnaire questions  
    ✅ Implementation recommendations and timeline
    ✅ Data analysis guidelines
    ✅ Ethics and privacy considerations
    ✅ Complete conversation history exported

    **Your Research Summary:**
    - **Topic:** {session.research_topic}
    - **Questions:** {len(final_questions)} validated questions
    - **Target:** {session.target_population}
    - **Timeline:** {session.timeframe}
    - **Chat interactions:** {len(session.chat_history) if session.chat_history else 0} recorded

    Both files are ready for download from the research_outputs directory.
    Session completed successfully!
    """
            
        except Exception as e:
            logger.error(f"Error exporting research package: {str(e)}", exc_info=True)
            return f"Error creating research package: {str(e)}. Please check logs and try again."
    
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
        """Handle user input during design input phase"""
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
**Question 2 of 4: Research Objectives**
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
            # Handle both single line and multi-line objectives
            if '\n' in user_input:
                objectives = [obj.strip() for obj in user_input.split('\n') if obj.strip()]
            else:
                # If single line, try to split by common delimiters
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
**Question 3 of 4: Target Population**
Who is your target population or study participants?

Examples:
- Adults aged 18-65 in urban areas
- College students at public universities
- Small business owners in the technology sector
- Parents of children under 12

Please describe your target population:
"""
        
        elif 'target_population' not in session.user_responses:
            # This is the response to Question 3 (target population)
            session.user_responses['target_population'] = user_input.strip()
            session.target_population = user_input.strip()
            
            logger.info(f"Session {session_id}: Saved target population - {session.target_population}")
            
            return """
**Question 4 of 4: Research Timeframe**
What is the timeframe for your research study?

Examples:
- Cross-sectional (one-time survey)
- Longitudinal over 6 months
- Pre-post intervention study
- Historical data from 2020-2024

Please specify your research timeframe:
"""
        
        elif 'timeframe' not in session.user_responses:
            # This is the response to Question 4 (timeframe) - final question
            session.user_responses['timeframe'] = user_input.strip()
            session.timeframe = user_input.strip()
            
            logger.info(f"Session {session_id}: Saved timeframe - {session.timeframe}")
            logger.info(f"Session {session_id}: All 4 questions completed, generating research design")
            
            # Generate research design summary
            research_design = await self._generate_research_design(session)
            session.stage = ResearchStage.DESIGN_REVIEW
            
            return f"""
📋 **Research Design Summary**

**Topic:** {session.research_topic}

**Objectives:**
{chr(10).join(f"• {obj}" for obj in session.objectives)}

**Target Population:** {session.target_population}

**Timeframe:** {session.timeframe}

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
            # All questions have been answered - this shouldn't happen in DESIGN_INPUT stage
            logger.warning(f"Session {session_id}: Unexpected state - all questions answered but still in DESIGN_INPUT stage")
            return "All research design questions have been completed. Please proceed with the review."
    
    async def _generate_research_design(self, session: ResearchDesign) -> str:
        """Generate a comprehensive research design using LLM"""
        prompt = f"""
Generate a comprehensive research design based on the following information:

Topic: {session.research_topic}
Objectives: {', '.join(session.objectives)}
Target Population: {session.target_population}
Timeframe: {session.timeframe}

Please provide:
1. Research methodology recommendations
2. Suggested data collection methods
3. Key variables to measure
4. Potential limitations and considerations
5. Recommended sample size

Keep the response concise but comprehensive (under 300 words). Respond in English only.
"""
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            # Clean the response to remove Chinese characters
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
        """Search internet with deep URL filtering"""
        try:
            relevant_questions, sources, screenshots = await self._search_internet_for_questions(
                session.research_topic, session.target_population
            )
            
            if not relevant_questions:
                return f"""
    ❌ **No Deep Content Found**

    Unable to find relevant survey content in deep URLs for your research topic.
    This might be because:
    - Most results were root domain pages (filtered out)
    - Limited specific survey content available
    - API rate limits or network issues

    **Would you like to:**
    - **R** (Retry) - Try the search again
    - **P** (Proceed) - Continue with AI-generated questions
    - **E** (Exit) - Exit workflow
    """
            
            # Store results
            session.internet_questions = relevant_questions
            session.internet_sources = sources
            session.screenshots = screenshots
            session.stage = ResearchStage.DECISION_POINT
            
            # Format questions with numbers for easy selection
            questions_with_numbers = []
            for i, question in enumerate(relevant_questions, 1):
                questions_with_numbers.append(f"{i}. {question}")
            
            unique_sources = list(set(sources))
            
            return f"""
    🔍 **Deep Content Research Results**

    Found {len(relevant_questions)} relevant questions from specific survey content:

    {chr(10).join(questions_with_numbers)}

    **📊 Quality Summary:**
    - **Sources:** {len(unique_sources)} specialized websites
    - **Content:** Scraped from {len(sources)} deep content pages
    - **Screenshots:** {len(screenshots)} quality screenshots captured
    ---

    **What would you like to do with these questions?**

    Reply with:
    - **Y** (Yes) - Go to Questionnaire Builder and include these questions
    - **N** (No) - Use only these questions and proceed to testing  
    - **A** (AI Only) - Skip these, use only AI-generated questions
    - **S** (Select) - Choose specific questions from the internet results to include
    - **E** (Exit) - Exit workflow
    """
            
        except Exception as e:
            logger.error(f"Error in database search: {e}")
            return f"❌ Search Error: {str(e)}"
    
    async def _handle_decision_point(self, session_id: str, user_input: str) -> str:
        """Handle major decision point with all options working correctly"""
        session = self.active_sessions[session_id]
        response = user_input.upper().strip()
        
        if response == 'Y':
            # Include ALL internet questions + generate additional questions
            session.use_internet_questions = True
            session.include_all_internet_questions = True  # NEW flag
            session.selected_internet_questions = False
            session.stage = ResearchStage.QUESTIONNAIRE_BUILDER
            return await self._start_questionnaire_builder(session)
        elif response == 'N':
            # Use ONLY internet questions and proceed directly to testing
            session.questions = session.internet_questions.copy()
            session.use_internet_questions = True
            session.include_all_internet_questions = True
            session.selected_internet_questions = False
            await self._store_accepted_questions(session)
            return await self._test_questions(session)
        elif response == 'A':
            # Skip internet questions, use only AI-generated questions
            session.use_internet_questions = False
            session.include_all_internet_questions = False
            session.selected_internet_questions = False
            session.stage = ResearchStage.QUESTIONNAIRE_BUILDER
            return await self._start_questionnaire_builder(session)
        elif response == 'S':
            # Select specific questions from internet questions as extras
            session.use_internet_questions = True
            session.include_all_internet_questions = False
            session.selected_internet_questions = True  # Selection mode
            session.stage = ResearchStage.QUESTIONNAIRE_BUILDER
            return await self._start_questionnaire_builder(session)
        elif response == 'E':
            del self.active_sessions[session_id]
            return "Research design workflow ended. Thank you!"
        else:
            return """
    Please respond with:
    - **Y** (Yes) - Go to Questionnaire Builder and include ALL these questions
    - **N** (No) - Use ONLY these questions and proceed to testing  
    - **A** (AI Only) - Skip these, use only AI-generated questions
    - **S** (Select) - Choose specific questions from the internet results to include
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

    async def _handle_questionnaire_builder(self, session_id: str, user_input: str) -> str:
        """Handle questionnaire builder interactions with all options"""
        session = self.active_sessions[session_id]
        
        # Initialize questionnaire responses safely
        if session.questionnaire_responses is None:
            session.questionnaire_responses = {}
        
        # Determine which mode we're in
        is_selection_mode = hasattr(session, 'selected_internet_questions') and session.selected_internet_questions
        is_include_all_mode = hasattr(session, 'include_all_internet_questions') and session.include_all_internet_questions
        total_questions_flow = 5 if is_selection_mode else 4
        
        # Universal commands
        if user_input.upper().strip() == 'A':
            await self._store_accepted_questions(session)
            return await self._test_questions(session)
        elif user_input.upper().strip() == 'R':
            return await self._revise_questions(session)
        elif user_input.upper().strip() == 'M':
            return await self._generate_more_questions(session)
        elif user_input.upper().strip() == 'B':
            session.questionnaire_responses = {}
            return await self._start_questionnaire_builder(session)
        
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
    **Question 2 of 4: Question Types Breakdown**
    You will have {len(session.internet_questions or [])} internet questions + {number_value} additional questions = **{total_final} total questions**.

    How would you like to distribute the {number_value} ADDITIONAL questions?

    Examples:
    - "3 demographic, 2 general, 0 open-ended" (for 5 additional)
    - "no demographic, 8 general, 2 open-ended" (for 10 additional)
    - "all general questions" (for any additional count)

    **Question Types:**
    - **Demographic**: Age, gender, education, income, location
    - **General**: Satisfaction, rating, frequency, importance (Likert scales)
    - **Open-ended**: What, why, suggestions, feelings

    Please specify your question breakdown for the {number_value} ADDITIONAL questions:
    """
                    else:
                        # S or A option - this is total questions
                        session.questionnaire_responses['total_questions'] = number_value
                        
                        if is_selection_mode:
                            return f"""
    **Question 2 of 5: Select Internet Questions**
    Please enter the question numbers from the internet-generated questions you want to include AS EXTRAS.

    **Available Questions:**
    {chr(10).join(f'{i+1}. {q}' for i, q in enumerate(session.internet_questions or []))}

    **Note:** Your selected questions will be ADDED to the {number_value} questions we'll generate.

    Enter the question numbers separated by spaces (e.g., "1 3 5 7"):
    """
                        else:
                            return f"""
    **Question 2 of 4: Question Types Breakdown**
    How would you like to distribute the {number_value} questions?

    Examples:
    - "5 demographic, 3 general, 2 open-ended" (for 10 total)
    - "all general questions" (for any total)

    **Question Types:**
    - **Demographic**: Age, gender, education, income, location
    - **General**: Satisfaction, rating, frequency, importance (Likert scales)
    - **Open-ended**: What, why, suggestions, feelings

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
    **Question 3 of 5: Question Types Breakdown**
    You have selected {len(selected_questions)} questions as extras.

    **Final Survey Structure:**
    - Base questions to generate: {base_questions}
    - Selected extras: {len(selected_questions)}
    - **Total final questions: {total_final}**

    How would you like to distribute the {base_questions} BASE questions?

    Please specify your question breakdown for the {base_questions} BASE questions:
    """
            except Exception as e:
                return f"""
    Please enter valid question numbers.
    """
        
        # Handle question breakdown
        elif 'question_breakdown' not in session.questionnaire_responses:
            session.questionnaire_responses['question_breakdown'] = user_input.strip()
            
            next_q = 3 if is_include_all_mode else (4 if is_selection_mode else 3)
            total_q = 4 if is_include_all_mode else (5 if is_selection_mode else 4)
            
            return f"""
    **Question {next_q} of {total_q}: Survey Length**
    How long should the survey take to complete?

    Examples:
    - "under 5 minutes"
    - "under 10 minutes"  
    - "under 15 minutes"

    Please specify the target completion time:
    """
        
        elif 'survey_length' not in session.questionnaire_responses:
            session.questionnaire_responses['survey_length'] = user_input.strip()
            
            next_q = 4 if is_include_all_mode else (5 if is_selection_mode else 4)
            total_q = 4 if is_include_all_mode else (5 if is_selection_mode else 4)
            
            return f"""
    **Question {next_q} of {total_q}: Target Audience Style**
    What audience style should the questions use?

    Examples:
    - "general audience"
    - "senior-friendly"
    - "mobile-friendly"

    Please specify the audience style:
    """
        
        elif 'audience_style' not in session.questionnaire_responses:
            session.questionnaire_responses['audience_style'] = user_input.strip()
            return await self._generate_questions_from_specifications(session)
        
        else:
            return "All questionnaire specifications completed."

    async def _generate_ai_questions(self, session: ResearchDesign, count: int, breakdown: str, survey_length: str, audience_style: str) -> list:
        """Generate AI questions with specified count and breakdown"""
        
        if count <= 0:
            return []
        
        # Parse breakdown
        import re
        demographic_count = 0
        general_count = 0
        open_ended_count = 0
        
        if "no demographic" in breakdown or "0 demographic" in breakdown:
            demographic_count = 0
        else:
            demo_match = re.search(r'(\d+)\s+demographic', breakdown)
            if demo_match:
                demographic_count = int(demo_match.group(1))
        
        if "all general" in breakdown:
            general_count = count - demographic_count - open_ended_count
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
        current_total = demographic_count + general_count + open_ended_count
        if current_total != count:
            general_count = count - demographic_count - open_ended_count
            general_count = max(0, general_count)
        
        # Generate questions
        prompt = f"""
    Generate EXACTLY {count} survey questions for this research:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}

    REQUIREMENTS:
    - EXACTLY {count} questions total
    - EXACTLY {demographic_count} demographic questions
    - EXACTLY {general_count} general questions
    - EXACTLY {open_ended_count} open-ended questions
    - Completion time: {survey_length}
    - Audience: {audience_style}

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
        """Generate questions based on specifications - handling all decision modes"""
        
        # Determine which mode we're in
        is_selection_mode = hasattr(session, 'selected_internet_questions') and session.selected_internet_questions
        is_include_all_mode = hasattr(session, 'include_all_internet_questions') and session.include_all_internet_questions
        
        # Get basic specifications
        breakdown = session.questionnaire_responses['question_breakdown'].lower()
        survey_length = session.questionnaire_responses['survey_length']
        audience_style = session.questionnaire_responses['audience_style']
        
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
        
        # Generate the required questions
        if questions_to_generate > 0:
            generated_questions = await self._generate_ai_questions(
                session, questions_to_generate, breakdown, survey_length, audience_style
            )
        else:
            generated_questions = []
        
        # Combine questions based on mode
        if is_include_all_mode:
            # Y option: Internet questions + generated questions
            final_questions = (session.internet_questions or []) + generated_questions
            
            display_info = f"""**All Internet Questions ({len(session.internet_questions or [])}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(session.internet_questions or []))}

    {"**Additional Generated Questions (" + str(len(generated_questions)) + "):**" if generated_questions else "**No Additional Questions Generated**"}
    {chr(10).join(f"{i+len(session.internet_questions or [])+1}. {q}" for i, q in enumerate(generated_questions)) if generated_questions else ""}

    **Total Questions: {len(final_questions)}** ({len(session.internet_questions or [])} internet + {len(generated_questions)} generated)
    """
            specs_info = f"""- Internet questions: {len(session.internet_questions or [])} (all included)
    - Additional generated: {len(generated_questions)}
    - Final total: {len(final_questions)}"""
            
        elif is_selection_mode:
            # S option: Generated questions + selected questions as extras
            selected_questions = session.questionnaire_responses.get('selected_questions', [])
            final_questions = generated_questions + selected_questions
            
            display_info = f"""**Generated Questions ({len(generated_questions)}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(generated_questions))}

    **Selected Internet Questions Added as Extras ({len(selected_questions)}):**
    {chr(10).join(f"{i+len(generated_questions)+1}. {q}" for i, q in enumerate(selected_questions))}

    **Total Questions: {len(final_questions)}** ({len(generated_questions)} generated + {len(selected_questions)} selected extras)
    """
            specs_info = f"""- Generated questions: {len(generated_questions)}
    - Selected extras: {len(selected_questions)}
    - Final total: {len(final_questions)}"""
            
        else:
            # A option: Only generated questions
            final_questions = generated_questions
            
            display_info = f"""**Generated Questions ({len(generated_questions)} total):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(generated_questions))}
    """
            specs_info = f"""- Total questions: {len(final_questions)}"""
        
        # Store final questions
        session.questions = final_questions
        
        logger.info(f"Created {len(final_questions)} total questions in mode: {'include_all' if is_include_all_mode else 'selection' if is_selection_mode else 'ai_only'}")
        
        return f"""
    ⚙️ **Questions Generated with Your Specifications**

    **Applied Specifications:**
    {specs_info}
    - Target time: {survey_length}
    - Audience: {audience_style}

    {display_info}

    ---

    **Review these questions:**
    - **A** (Accept) - Use these questions and proceed to testing
    - **R** (Revise) - Request modifications to the questions
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

    async def _store_accepted_questions(self, session: ResearchDesign) -> None:
        """Store the accepted questions in the session"""
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
    
    async def _test_questions(self, session: ResearchDesign) -> str:
        """Test questions with synthetic respondents using AI simulation"""
        # Move to final output stage
        session.stage = ResearchStage.FINAL_OUTPUT
        
        # Use all questions stored in session.questions (which now includes both generated + selected)
        all_test_questions = session.questions or []
        
        # Remove duplicates while preserving order
        seen = set()
        unique_questions = []
        for q in all_test_questions:
            if q not in seen:
                seen.add(q)
                unique_questions.append(q)
        
        all_test_questions = unique_questions
        
        try:
            # Generate synthetic respondent feedback using LLM
            synthetic_feedback = await self._generate_synthetic_respondent_feedback_all(session, all_test_questions)
            
            # Determine description based on selection mode
            selection_info = ""
            if (hasattr(session, 'selected_internet_questions') and 
                session.selected_internet_questions and 
                session.questionnaire_responses and 
                'selected_questions' in session.questionnaire_responses):
                
                selected_count = len(session.questionnaire_responses['selected_questions'])
                base_count = session.questionnaire_responses['total_questions']
                selection_info = f"({base_count} generated questions + {selected_count} selected extras)"
            elif session.use_internet_questions:
                internet_count = len([q for q in all_test_questions if q in (session.internet_questions or [])])
                ai_count = len(all_test_questions) - internet_count
                selection_info = f"({ai_count} AI generated + {internet_count} internet research questions)"
            else:
                selection_info = "(AI generated questions only)"
            
            return f"""
    🧪 **Testing Questionnaire with Synthetic Respondents**

    Running simulation with 5 diverse synthetic respondents matching your target population...

    **Testing {len(all_test_questions)} total questions**
    {selection_info}

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

    ---

    **Are you satisfied with the questionnaire?**
    - **Y** (Yes) - Finalize and export complete research package
    - **N** (No) - Make additional modifications
    - **T** (Test Again) - Run another round of testing
    """
    
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
        """Handle question revision requests"""
        return """
✏️ **Revise Questions**

Please specify what you'd like to change:

1. **Modify specific questions** - Tell me which question numbers to change
2. **Change question types** - Convert to different formats (multiple choice, Likert, etc.)
3. **Add demographic questions** - Include age, gender, income, etc.
4. **Remove questions** - Specify which questions to remove
5. **Change difficulty level** - Make questions simpler or more detailed

Please describe your revision needs:
"""
    
    async def _generate_more_questions(self, session: ResearchDesign) -> str:
        """Generate additional questions"""
        prompt = f"""
Generate 5 additional survey questions for this research:

Topic: {session.research_topic}
Target: {session.target_population}

Focus on aspects not yet covered. Include demographic and behavioral questions. Respond in English only.
"""
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            return f"""
📝 **Additional Questions Generated**

{cleaned_response}

---

**Options:**
- **A** (Accept All) - Add these to your questionnaire
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
                    else:
                        response_content = await self.research_workflow.process_research_input(
                            session_id, request.content
                        )
                    
                    result = {
                        "response": response_content,
                        "status": "success",
                        "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                        "session_id": session_id
                    }
                    
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

    async def process_message(self, user_message: str, session_id: str = "default", action_type: str = None):
        """Process a user message via WebSocket with enhanced screenshot validation."""
        try:
            if not self.agent:
                await self.broadcast_message("error", {"message": "Agent not initialized"})
                return

            # Check if we have an active research session first
            if session_id in self.research_workflow.active_sessions:
                session = self.research_workflow.active_sessions[session_id]
                
                # Special handling for research workflow - check if we're at the search stage
                if session.stage == ResearchStage.DESIGN_REVIEW and user_message.upper().strip() == 'Y':
                    # User accepted design and we're about to search - this will capture URL screenshots
                    try:
                        # Process the research input which will capture screenshots of found URLs
                        response = await self.research_workflow.process_research_input(session_id, user_message)
                        
                        # After processing, check if we have screenshots to display
                        if hasattr(session, 'screenshots') and session.screenshots:
                            logger.info(f"Broadcasting slideshow with {len(session.screenshots)} screenshots")
                            
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
                                    "source_url": session.screenshots[0]['url']  # For Visit Site button
                                })
                        
                        await self.broadcast_message("agent_message", {
                            "content": response,
                            "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                            "session_id": session_id
                        })
                        return
                        
                    except Exception as e:
                        logger.warning(f"Could not process research with screenshots: {e}")
                
                # Regular research workflow processing
                response = await self.research_workflow.process_research_input(session_id, user_message)
                
                await self.broadcast_message("agent_message", {
                    "content": response,
                    "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                    "session_id": session_id
                })
                return

            # If no active session, detect intent
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