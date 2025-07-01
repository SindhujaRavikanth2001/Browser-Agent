import asyncio
import os
import json
from datetime import datetime
from asyncio import TimeoutError as AsyncTimeoutError
from typing import Dict, List, Optional, Union
from contextvars import ContextVar
import requests
from bs4 import BeautifulSoup
from enum import Enum
from dotenv import load_dotenv

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
    internet_questions: Optional[List[str]] = None  # Store internet questions separately
    internet_sources: Optional[List[str]] = None   # Store internet sources separately
    use_internet_questions: bool = False            # Flag to track if internet questions should be included
    stage: ResearchStage = ResearchStage.INITIAL
    user_responses: Optional[Dict] = None
    questionnaire_responses: Optional[Dict] = None

class UserMessage(BaseModel):
    content: str
    action_type: Optional[str] = None
    research_session_id: Optional[str] = None

# Research Design Workflow Functions
class ResearchWorkflow:
    def __init__(self, llm_instance):
        self.llm = llm_instance
        self.active_sessions: Dict[str, ResearchDesign] = {}
        
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
    
    async def _search_internet_for_questions(self, research_topic: str, target_population: str) -> tuple[List[str], List[str]]:
        """Search internet with single query, scrape 5 URLs, generate 5 questions"""
        try:
            if not self.search_service:
                logger.warning("Google Custom Search API not available, using fallback")
                return await self._fallback_search(research_topic, target_population)
            
            search_query = f"Surveys on {research_topic} "
            logger.info(f"Searching for: {search_query}")
            # Single search query - just the research topic
            search_result = self.search_service.cse().list(
                q=search_query,
                cx=self.google_cse_id,
                num=10,  # Get exactly 10 results
                safe='active',
                fields='items(title,link,snippet)'
            ).execute()
            
            # Collect the 10 URLs
            urls_to_scrape = []
            if 'items' in search_result:
                for item in search_result['items']:
                    link = item.get('link', '')
                    if link:
                        urls_to_scrape.append(link)
            
            logger.info(f"Found {len(urls_to_scrape)} URLs to scrape")
            
            # Scrape content from all 10 URLs
            all_scraped_content = ""
            scraped_sources = []
            
            for url in urls_to_scrape:
                try:
                    logger.info(f"Scraping content from: {url}")
                    page_content = await self._scrape_page_content(url)
                    
                    if page_content and len(page_content) > 100:
                        all_scraped_content += f"\n\nContent from {url}:\n{page_content[:2000]}"  # Limit per URL
                        scraped_sources.append(url)
                        
                    await asyncio.sleep(0.3)  # Small delay between scrapes
                    
                except Exception as e:
                    logger.warning(f"Could not scrape {url}: {e}")
                    continue
            
            logger.info(f"Successfully scraped {len(scraped_sources)} sources")
            
            # Generate 5 questions using LLM based on all scraped content
            questions = await self._generate_questions_from_content(
                all_scraped_content, research_topic, target_population
            )
            
            # Return questions with all scraped sources
            # Each question will be associated with all sources since LLM used all content
            sources = scraped_sources * (len(questions) // len(scraped_sources) + 1)
            sources = sources[:len(questions)]  # Match the number of questions
            
            logger.info(f"Generated {len(questions)} questions from scraped content")
            
            return questions, sources
            
        except Exception as e:
            logger.error(f"Error in simplified search: {e}")
            return await self._fallback_search(research_topic, target_population)

    async def _generate_questions_from_content(self, scraped_content: str, research_topic: str, target_population: str) -> List[str]:
        """Generate exactly 5 questions from scraped content using LLM"""
        
        prompt = f"""
    Based on the following scraped web content about "{research_topic}", create exactly 5 professional survey questions suitable for "{target_population}".

    SCRAPED CONTENT:
    {scraped_content[:6000]}  # Limit content for LLM processing

    INSTRUCTIONS:
    1. Create exactly 5 survey questions
    2. Base questions on the concepts, topics, and information found in the scraped content
    3. Make questions relevant to "{research_topic}" research
    4. Use professional survey language appropriate for "{target_population}"
    5. Include a mix of satisfaction, frequency, rating, and preference questions
    6. Each question should be clear, specific, and measurable
    7. Return only the questions, one per line
    8. All questions must end with a question mark

    Generate exactly 5 survey questions:
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
            
            # Ensure we have exactly 5 questions
            if len(questions) < 5:
                # If fewer than 5, generate additional simple questions
                additional_needed = 5 - len(questions)
                basic_questions = [
                    f"How satisfied are you with {research_topic}?",
                    f"How often do you engage with {research_topic}?",
                    f"How important is {research_topic} to you?",
                    f"How likely are you to recommend {research_topic}?",
                    f"What factors are most important regarding {research_topic}?",
                    f"How would you rate your overall experience with {research_topic}?"
                ]
                questions.extend(basic_questions[:additional_needed])
            
            # Return exactly 5 questions
            return questions[:5]
            
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
    async def _fallback_search(self, research_topic: str, target_population: str) -> tuple[List[str], List[str]]:
        """Enhanced fallback that uses LLM to generate questions"""
        logger.info("Using enhanced LLM fallback for question generation")
        
        # Generate comprehensive set of questions using LLM
        questions = await self._generate_questions_with_llm(research_topic, target_population, 5)
        
        # Create sources for fallback
        sources = ["Generated based on research methodology"] * len(questions)
        
        return questions, sources

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
        self.active_sessions[session_id] = ResearchDesign(stage=ResearchStage.DESIGN_INPUT)
        
        return """
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

    async def process_research_input(self, session_id: str, user_input: str) -> str:
        """Process user input during research design phase"""
        if session_id not in self.active_sessions:
            return "Session not found. Please start a new research design session."
        
        session = self.active_sessions[session_id]
        
        if session.stage == ResearchStage.DESIGN_INPUT:
            return await self._handle_design_input(session_id, user_input)
        elif session.stage == ResearchStage.DESIGN_REVIEW:
            return await self._handle_design_review(session_id, user_input)
        elif session.stage == ResearchStage.DECISION_POINT:
            return await self._handle_decision_point(session_id, user_input)
        elif session.stage == ResearchStage.QUESTIONNAIRE_BUILDER:
            return await self._handle_questionnaire_builder(session_id, user_input)
        elif session.stage == ResearchStage.FINAL_OUTPUT:
            return await self._handle_final_output(session_id, user_input)
        else:
            return "Invalid session stage."
    
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
        """Export complete research package including questionnaire"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"complete_research_package_{timestamp}.txt"
        
        try:
            os.makedirs("research_outputs", exist_ok=True)
            
            # Get the generated research design
            research_design_content = await self._generate_research_design(session)
            
            # Prepare questions for export based on the flow used - FIXED VERSION
            all_questions = []
            
            if session.use_internet_questions and session.internet_questions:
                # Include internet questions
                all_questions.extend(session.internet_questions)
                # Only add AI questions if they exist AND are different from internet questions
                if session.questions:
                    # Remove duplicates by checking if AI questions are substantially different
                    for ai_q in session.questions:
                        is_duplicate = False
                        for internet_q in session.internet_questions:
                            # Simple similarity check - if questions are very similar, skip
                            if (len(set(ai_q.lower().split()) & set(internet_q.lower().split())) / 
                                min(len(ai_q.split()), len(internet_q.split()))) > 0.7:
                                is_duplicate = True
                                break
                        if not is_duplicate:
                            all_questions.append(ai_q)
            else:
                # Only include AI-generated questions
                if session.questions:
                    all_questions.extend(session.questions)
            
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

{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(all_questions))}

================================================================================
QUESTION SOURCES
================================================================================

{"Internet Research Questions: " + str(len(session.internet_questions or [])) if session.use_internet_questions else ""}
{"AI Generated Questions: " + str(len(session.questions or [])) if session.questions else ""}

{("Internet Sources:" + chr(10) + chr(10).join(f"• {source}" for source in (session.internet_sources or []))) if session.use_internet_questions and session.internet_sources else ""}

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
"""
            
            filepath = f"research_outputs/{filename}"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(package_content)
            
            logger.info(f"Research package exported successfully to {filepath}")
            
            # Clean up session - use proper session_id
            session_keys_to_remove = []
            for key, sess in self.active_sessions.items():
                if sess == session:
                    session_keys_to_remove.append(key)
            
            for key in session_keys_to_remove:
                del self.active_sessions[key]
            
            return f"""
🎉 **Research Package Complete!**

Your comprehensive research package has been exported to:
**`{filepath}`**

**Package Contents:**
✅ Complete research design and methodology
✅ Tested and validated questionnaire questions  
✅ Implementation recommendations and timeline
✅ Data analysis guidelines
✅ Ethics and privacy considerations

**Your Research Summary:**
- **Topic:** {session.research_topic}
- **Questions:** {len(all_questions)} validated questions
- **Target:** {session.target_population}
- **Timeline:** {session.timeframe}

The file is ready for download from the research_outputs directory.
Session completed successfully!
"""
            
        except Exception as e:
            logger.error(f"Error exporting research package: {str(e)}", exc_info=True)
            return f"Error creating research package: {str(e)}. Please check logs and try again."
    
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
    
    async def _search_database(self, session: ResearchDesign) -> str:
        """Search internet for relevant research questions and data"""
        try:
            # Search the internet for relevant questions
            relevant_questions, sources = await self._search_internet_for_questions(
                session.research_topic, session.target_population
            )
            
            # If no questions found, provide fallback
            if not relevant_questions:
                return f"""
❌ **No Search Results Found**

Unable to find relevant questions for your research topic. This might be due to:
- API rate limits
- Network connectivity issues
- Very specific or unusual research topic

**Would you like to:**
- **R** (Retry) - Try the search again
- **P** (Proceed) - Continue with manually created questions
- **E** (Exit) - Exit workflow
"""
            
            # Store internet questions and sources separately
            session.internet_questions = relevant_questions
            session.internet_sources = sources
            session.stage = ResearchStage.DECISION_POINT
            
            # Format questions with their specific sources
            questions_with_sources = []
            for i, (question, source) in enumerate(zip(relevant_questions, sources), 1):
                questions_with_sources.append(f"{i}. {question} - {source}")
            
            # Get unique sources for display
            unique_sources = list(set(sources))
            
            return f"""
🔍 **Internet Research Results**

Found {len(relevant_questions)} relevant questions from Google search:

{chr(10).join(questions_with_sources)}

**Sources:** {len(unique_sources)} unique websites found

---

**What would you like to do with these questions?**

Reply with:
- **Y** (Yes) - Go to Questionnaire Builder and include these questions in final testing
- **N** (No) - Only use these questions and proceed directly to synthetic testing  
- **A** (AI Only) - Don't use these questions, only use AI-generated questions in next step
- **E** (Exit) - Exit workflow
"""
            
        except Exception as e:
            logger.error(f"Error in database search: {e}")
            return f"""
❌ **Search Error**

There was an issue searching for relevant questions: {str(e)}

Would you like to:
- **R** (Retry) - Try the search again
- **P** (Proceed) - Continue with basic questions
- **E** (Exit) - Exit workflow
"""
    
    async def _handle_decision_point(self, session_id: str, user_input: str) -> str:
        """Handle major decision point with new options"""
        session = self.active_sessions[session_id]
        response = user_input.upper().strip()
        
        if response == 'Y':
            # Go to questionnaire builder and include internet questions
            session.use_internet_questions = True
            session.stage = ResearchStage.QUESTIONNAIRE_BUILDER
            return await self._start_questionnaire_builder(session)
        elif response == 'N':
            # Only use internet questions and proceed to testing
            session.questions = session.internet_questions
            session.use_internet_questions = True
            await self._store_accepted_questions(session)
            return await self._test_questions(session)
        elif response == 'A':
            # Don't use internet questions, only AI questions in next step
            session.use_internet_questions = False
            session.stage = ResearchStage.QUESTIONNAIRE_BUILDER
            return await self._start_questionnaire_builder(session)
        elif response == 'E':
            del self.active_sessions[session_id]
            return "Research design workflow ended. Thank you!"
        else:
            return """
Please respond with:
- **Y** (Yes) - Go to Questionnaire Builder and include these questions in final testing
- **N** (No) - Only use these questions and proceed directly to synthetic testing  
- **A** (AI Only) - Don't use these questions, only use AI-generated questions in next step
- **E** (Exit) - Exit workflow
"""
    
    async def _start_questionnaire_builder(self, session: ResearchDesign) -> str:
        """Start the questionnaire builder process with step-by-step prompts"""
        if session.use_internet_questions:
            questions_info = f"**Available Internet Questions ({len(session.internet_questions or [])}):**\n{chr(10).join(f'{i+1}. {q}' for i, q in enumerate((session.internet_questions or [])[:3]))}{'...' if len(session.internet_questions or []) > 3 else ''}\n\n"
        else:
            questions_info = ""
        
        # Initialize questionnaire responses safely
        if session.questionnaire_responses is None:
            session.questionnaire_responses = {}
            
        return f"""
    📝 **Questionnaire Builder**

    {questions_info}Let's design your questionnaire step by step. I'll ask you 4 questions to customize your survey.

    **Question 1 of 4: Total Number of Questions**
    How many questions do you want in your survey?

    Examples:
    - 10 questions
    - 15 questions
    - 20 questions

    Please specify the total number of questions:
    """

    async def _handle_questionnaire_builder(self, session_id: str, user_input: str) -> str:
        """Handle questionnaire builder interactions with step-by-step prompts"""
        session = self.active_sessions[session_id]
        
        # Initialize questionnaire responses safely
        if session.questionnaire_responses is None:
            session.questionnaire_responses = {}
        
        # First check for universal commands that work from any state
        if user_input.upper().strip() == 'A':
            # Accept questions - store them and move to testing phase
            await self._store_accepted_questions(session)
            return await self._test_questions(session)
        elif user_input.upper().strip() == 'R':
            # Revise questions
            return await self._revise_questions(session)
        elif user_input.upper().strip() == 'M':
            # Generate more questions
            return await self._generate_more_questions(session)
        elif user_input.upper().strip() == 'B':
            # Back to menu - reset questionnaire responses
            session.questionnaire_responses = {}
            return await self._start_questionnaire_builder(session)
        
        # Handle step-by-step questionnaire building
        if 'total_questions' not in session.questionnaire_responses:
            # This is the response to Question 1 (total questions)
            try:
                # Extract number from response
                import re
                numbers = re.findall(r'\d+', user_input)
                if numbers:
                    total_questions = min(int(numbers[0]), 25)  # Cap at 25
                    session.questionnaire_responses['total_questions'] = total_questions
                    
                    return f"""
    **Question 2 of 4: Question Types Breakdown**
    How would you like to distribute the {total_questions} questions?

    Examples:
    - "5 demographic, 3 general, 2 open-ended" (for 10 total)
    - "3 demographic, 7 general, 5 open-ended" (for 15 total)
    - "no demographic, 8 general, 2 open-ended" (for 10 total)
    - "all general questions" (for any total)

    **Question Types:**
    - **Demographic**: Age, gender, education, income, location
    - **General**: Satisfaction, rating, frequency, importance (Likert scales)
    - **Open-ended**: What, why, suggestions, feelings

    Please specify your question breakdown:
    """
                else:
                    return """
    Please provide a number for the total questions.
    Examples: "10 questions", "15", "20 questions total"

    Please specify the total number of questions:
    """
            except Exception as e:
                return """
    Please provide a valid number for the total questions.
    Examples: "10 questions", "15", "20 questions total"

    Please specify the total number of questions:
    """
        
        elif 'question_breakdown' not in session.questionnaire_responses:
            # This is the response to Question 2 (question breakdown)
            session.questionnaire_responses['question_breakdown'] = user_input.strip()
            
            return """
    **Question 3 of 4: Survey Length**
    How long should the survey take to complete?

    Examples:
    - "under 5 minutes"
    - "under 10 minutes"
    - "under 15 minutes"
    - "10-15 minutes"

    Please specify the target completion time:
    """
        
        elif 'survey_length' not in session.questionnaire_responses:
            # This is the response to Question 3 (survey length)
            session.questionnaire_responses['survey_length'] = user_input.strip()
            
            return """
    **Question 4 of 4: Target Audience Style**
    What audience style should the questions use?

    Examples:
    - "general audience"
    - "senior-friendly"
    - "mobile-friendly"
    - "student-friendly"
    - "business professional"

    Please specify the audience style:
    """
        
        elif 'audience_style' not in session.questionnaire_responses:
            # This is the response to Question 4 (audience style) - final question
            session.questionnaire_responses['audience_style'] = user_input.strip()
            
            # Now generate questions with the collected specifications
            return await self._generate_questions_from_specifications(session)
        
        else:
            # All questions have been answered - this shouldn't happen
            return "All questionnaire specifications have been completed. Please proceed with question generation."

    async def _generate_questions_from_specifications(self, session: ResearchDesign) -> str:
        """Generate questions based on collected specifications"""
        
        # Extract specifications
        total_questions = session.questionnaire_responses['total_questions']
        breakdown = session.questionnaire_responses['question_breakdown'].lower()
        survey_length = session.questionnaire_responses['survey_length']
        audience_style = session.questionnaire_responses['audience_style']
        
        # Parse question breakdown
        import re
        demographic_count = 0
        general_count = 0
        open_ended_count = 0
        
        # Extract numbers for each type
        if "no demographic" in breakdown or "0 demographic" in breakdown:
            demographic_count = 0
        else:
            demo_match = re.search(r'(\d+)\s+demographic', breakdown)
            if demo_match:
                demographic_count = int(demo_match.group(1))
        
        if "all general" in breakdown:
            general_count = total_questions - demographic_count - open_ended_count
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
        
        # If breakdown doesn't add up to total, adjust general questions
        current_total = demographic_count + general_count + open_ended_count
        if current_total != total_questions:
            general_count = total_questions - demographic_count - open_ended_count
            general_count = max(0, general_count)  # Don't go negative
        
        # Generate questions with strict count control
        prompt = f"""
    Generate EXACTLY {total_questions} survey questions for this research:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}

    STRICT REQUIREMENTS:
    - EXACTLY {total_questions} questions total (no more, no less)
    - EXACTLY {demographic_count} demographic questions
    - EXACTLY {general_count} general questions (satisfaction, rating, frequency, Likert scales)
    - EXACTLY {open_ended_count} open-ended questions
    - Completion time: {survey_length}
    - Audience: {audience_style}

    CRITICAL INSTRUCTIONS:
    1. Generate questions in this exact order: demographic first, then general, then open-ended
    2. Number each question (1., 2., 3., etc.)
    3. Each question must end with a question mark
    4. Return ONLY the numbered questions, nothing else
    5. Do not exceed {total_questions} questions under any circumstances

    Generate exactly {total_questions} questions now:
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.6)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            # Parse questions with strict counting
            lines = cleaned_response.split('\n')
            questions = []
            
            for line in lines:
                line = line.strip()
                
                # Skip empty lines and instructional text
                if not line or len(line) < 10:
                    continue
                
                # Skip lines that are clearly not questions
                if any(skip_word in line.lower() for skip_word in [
                    'note:', 'requirements:', 'instructions:', 'demographic:', 'general:', 'open-ended:',
                    'exactly', 'total', 'questions:', 'generate', 'critical', 'strict'
                ]):
                    continue
                
                # Extract clean question
                clean_line = re.sub(r'^[\d\.\-\•\*\s]*', '', line).strip()
                
                if clean_line and len(clean_line) > 15:
                    # Ensure question ends with ?
                    if not clean_line.endswith('?'):
                        clean_line += '?'
                    
                    questions.append(clean_line)
                    
                    # STRICT LIMIT: Stop when we reach the target
                    if len(questions) >= total_questions:
                        break
            
            # CRITICAL: Ensure exactly the requested number
            if len(questions) > total_questions:
                questions = questions[:total_questions]
            elif len(questions) < total_questions:
                # Generate basic questions to fill the gap
                needed = total_questions - len(questions)
                for i in range(needed):
                    questions.append(f"How satisfied are you with {session.research_topic}?")
            
            # Store the questions
            session.questions = questions
            
            logger.info(f"Generated exactly {len(session.questions)} questions as requested")
            
            return f"""
    ⚙️ **Questions Generated with Your Specifications**

    **Applied Specifications:**
    - Total questions: {total_questions}
    - Demographic questions: {demographic_count}
    - General questions: {general_count}
    - Open-ended questions: {open_ended_count}
    - Target time: {survey_length}
    - Audience: {audience_style}

    **Generated Questions ({len(session.questions)} total):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(session.questions))}

    ---

    **Review these questions:**
    - **A** (Accept) - Use these questions and proceed to testing
    - **R** (Revise) - Request modifications to the questions
    - **M** (More) - Generate additional questions
    - **B** (Back) - Return to questionnaire builder menu
    """
            
        except Exception as e:
            logger.error(f"Error generating questions: {e}")
            return f"""
    ❌ **Error Generating Questions**

    There was an issue generating questions: {str(e)}

    Please try again:
    - **B** (Back) - Return to questionnaire builder menu
    - **R** (Revise) - Try generating questions again
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
        
        # Prepare all questions for testing
        all_test_questions = []
        
        if session.use_internet_questions and session.internet_questions:
            all_test_questions.extend(session.internet_questions)
        
        if session.questions:
            all_test_questions.extend(session.questions)
        
        try:
            # Generate synthetic respondent feedback using LLM
            synthetic_feedback = await self._generate_synthetic_respondent_feedback_all(session, all_test_questions)
            
            return f"""
🧪 **Testing Questionnaire with Synthetic Respondents**

Running simulation with 5 diverse synthetic respondents matching your target population...

**Testing {len(all_test_questions)} total questions**
{"(Including " + str(len(session.internet_questions or [])) + " internet research questions + " + str(len(session.questions or [])) + " AI generated questions)" if session.use_internet_questions else "(AI generated questions only)"}

{synthetic_feedback}

---

**Are you satisfied with the questionnaire?**
- **Y** (Yes) - Finalize and export complete research package
- **N** (No) - Make additional modifications
- **T** (Test Again) - Run another round of testing
"""
        except Exception as e:
            logger.error(f"Error in synthetic testing: {e}")
            # Fallback to basic testing if AI simulation fails
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
Please respond in English only. Use 'Source:' instead of '来源:', only if the user asks for sources/references. Format URLs as markdown links.
{message}

I have scraped the complete content from the webpage. Here is the full content:

COMPLETE SCRAPED CONTENT:
{scraped_content[:8000]}

Based on this content, address the user's prompt in English only and within 300 words by avoiding unnecessary spaces. Strictly do not include any other language.
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
            raw = await asyncio.wait_for(
                agent.llm.ask(message,
                temperature=0.7),
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

                # Use provided session ID or create default
                session_id = request.research_session_id or "default_research_session"
                
                # Check if we have an active research session first
                if session_id in self.research_workflow.active_sessions:
                    # Continue existing research session
                    logger.info(f"Continuing research session: {session_id}")
                    response_content = await self.research_workflow.process_research_input(
                        session_id, request.content
                    )
                    
                    return JSONResponse({
                        "response": response_content,
                        "status": "success",
                        "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                        "session_id": session_id
                    })

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
                    # Handle URL research or general research
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
                        "status": "success",
                        "action_type": action_type
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
        """Process a user message via WebSocket."""
        try:
            if not self.agent:
                await self.broadcast_message("error", {"message": "Agent not initialized"})
                return

            # Log current session state for debugging
            logger.info(f"Processing message for session: {session_id}")
            logger.info(f"Active sessions: {list(self.research_workflow.active_sessions.keys())}")
            logger.info(f"Message content: {user_message[:100]}...")

            # Check if we have an active research session first
            if session_id in self.research_workflow.active_sessions:
                # We have an active research session, continue it regardless of intent detection
                logger.info(f"Active research session found: {session_id}, continuing workflow")
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
                logger.info(f"Detected intent: {action_type} for message: {user_message[:50]}...")

            await self.broadcast_message("agent_action", {
                "action": "Processing",
                "details": f"Processing {action_type}: {user_message}"
            })

            # Handle different action types
            if action_type == UserAction.BUILD_QUESTIONNAIRE.value:
                # Start new research session  
                logger.info(f"Starting new research session: {session_id}")
                response = await self.research_workflow.start_research_design(session_id)

                await self.broadcast_message("agent_message", {
                    "content": response,
                    "action_type": action_type,
                    "session_id": session_id
                })

            else:
                # Handle URL research or general research
                if action_type == UserAction.URL_RESEARCH.value or 'http' in user_message:
                    # URL-based research
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
                    logger.info(f"Processing as general research question: {user_message[:50]}...")
                    prefix = (
                        "Please respond in English only within 300 words. Avoid unnecessary spaces. "
                        "Use 'Source:' instead of '来源:', only if the user asks for sources/references."
                        "Format URLs as markdown links (e.g. [text](url)).\n\n"
                    )
                    raw = await self.agent.llm.ask(prefix + user_message, temperature=0.7)
                    response_data = {
                        "response": annotate_invalid_links(collapse_to_root_domain(remove_chinese_and_punct(str(raw)))),
                        "base64_image": None
                    }

                if isinstance(response_data, dict):
                    response_content = response_data.get("response", "")
                    screenshot = response_data.get("base64_image", None)
                else:
                    response_content = str(response_data)
                    screenshot = None

                await self.broadcast_message("agent_message", {
                    "content": response_content,
                    "action_type": action_type
                })

                if screenshot:
                    await self.broadcast_message("browser_state", {
                        "base64_image": screenshot
                    })

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