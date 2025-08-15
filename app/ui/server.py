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
import hashlib
from difflib import SequenceMatcher
# Load environment variables
load_dotenv()
from pydantic import BaseModel, Field
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import concurrent.futures
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import tempfile
import os
import json
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
import time
# Google API imports
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Define a global context variable for the Manus agent
g = ContextVar('g', default=None)

# Polling site selection
class PollingSiteConfig:
    """Configuration for polling websites"""
    
    # ENHANCED: Base URLs for polling sites (for screenshots)
    POLLING_SITE_BASE_URLS = {
        'marist': 'https://maristpoll.marist.edu/',
        'siena': 'https://scri.siena.edu/',
        'quinnipiac': 'https://poll.qu.edu/',
        'marquette': 'https://www.marquette.edu/law/poll/',
        'gallup': 'https://www.gallup.com/',
        'pew': 'https://www.pewresearch.org/',
        'suffolk': 'https://www.suffolk.edu/academics/research-at-suffolk/political-research-center',
        'monmouth': 'https://www.monmouth.edu/polling-institute/',
        'cbs': 'https://www.cbsnews.com/news/polls/',
        'ipsos': 'https://www.ipsos.com/',
        'emerson': 'https://emersoncollegepolling.com/',
        'yougov': 'https://today.yougov.com/',
        'kff': 'https://www.kff.org/',
        'beacon': 'https://beaconresearch.com/',
        'researchco': 'https://researchco.ca/',
        'dataforprogress': 'https://www.dataforprogress.org/',
        'harris': 'https://theharrispoll.com/',
        'monmouth': 'https://www.monmouth.edu/polling-institute/',
        'ppp': 'https://www.publicpolicypolling.com/',
        'ssrs': 'https://ssrs.com/',
        'ballotpedia': 'https://ballotpedia.org/',
        'apnorc': 'https://apnorc.org/',
    }
    
    AVAILABLE_POLLS = {
        'marist': {
            'name': 'Marist University',
            'description': 'Marist Poll - National and regional political polling',
            'scraper_file': 'scrapers/marist_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['marist'],  # ADD: Reference to base URL
            'active': True
        },
        'siena': {
            'name': 'Siena College',
            'description': 'Siena Research Institute - New York State polling',
            'scraper_file': 'scrapers/siena_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['siena'],
            'active': True
        },
        'quinnipiac': {
            'name': 'Quinnipiac University',
            'description': 'Quinnipiac Poll - National political polling',
            'scraper_file': 'scrapers/quinnipiac_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['quinnipiac'],
            'active': True
        },
        'marquette': {
            'name': 'Marquette Law School',
            'description': 'Marquette Law School Poll - Wisconsin and national polling',
            'scraper_file': 'scrapers/marquette_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['marquette'],
            'active': True
        },
        'gallup': {
            'name': 'Gallup',
            'description': 'Gallup - Public opinion polling and research',
            'scraper_file': 'scrapers/gallup_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['gallup'],
            'active': True
        },
        'pew': {
            'name': 'Pew Research Center',
            'description': 'Pew Research - Social trends and public opinion',
            'scraper_file': 'scrapers/pew_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['pew'],
            'active': True
        },
        'suffolk': {
            'name': 'Suffolk University',
            'description': 'Suffolk University Political Research Center',
            'scraper_file': 'scrapers/suffolk_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['suffolk'],
            'active': True
        },
        'ipsos': {  
            'name': 'Ipsos',
            'description': 'Ipsos - Global market research and public opinion polling',
            'scraper_file': 'scrapers/ipsos_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['ipsos'],
            'active': True
        },
        'emerson': {  
            'name': 'Emerson College',
            'description': 'Emerson College Polling - Political and public opinion research',
            'scraper_file': 'scrapers/emerson_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['emerson'],
            'active': True
        },
        'yougov': {  
            'name': 'YouGov',
            'description': 'YouGov - International internet-based market research and data analytics',
            'scraper_file': 'scrapers/yougov_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['yougov'],
            'active': True
        },
        'kff': { 
            'name': 'Kaiser Family Foundation',
            'description': 'KFF - Healthcare policy and public opinion research (healthcare topics only)',
            'scraper_file': 'scrapers/kff_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['kff'],
            'active': True,
            'topic_filter': 'healthcare'
        },
        'beacon': {  
            'name': 'Beacon Research',
            'description': 'Beacon Research - Public opinion and market research',
            'scraper_file': 'scrapers/beacon_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['beacon'],
            'active': True
        },
        'researchco': {
            'name': 'Research Co.',
            'description': 'Research Co. - Canadian public opinion and market research',
            'scraper_file': 'scrapers/researchco_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['researchco'],
            'active': True
        },
        'dataforprogress': {
            'name': 'Data for Progress',
            'description': 'Data for Progress - Progressive polling and research organization',
            'scraper_file': 'scrapers/dataforprogress_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['dataforprogress'],
            'active': True
        },
        'harris': {
            'name': 'Harris Poll',
            'description': 'Harris Poll - Market research and public opinion polling',
            'scraper_file': 'scrapers/harrispoll_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['harris'],
            'active': True
        },
        'monmouth': {
            'name': 'Monmouth University',
            'description': 'Monmouth University Polling Institute',
            'scraper_file': 'scrapers/monmouth_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['monmouth'],
            'active': True
        },
        'ppp': {
            'name': 'Public Policy Polling',
            'description': 'Public Policy Polling - Democratic polling firm',
            'scraper_file': 'scrapers/ppp_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['ppp'],
            'active': True
        },
        'ssrs': {
            'name': 'SSRS',
            'description': 'SSRS - Survey research and data collection',
            'scraper_file': 'scrapers/ssrs_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['ssrs'],
            'active': True
        },
        'ballotpedia': {
            'name': 'Ballotpedia',
            'description': 'Ballotpedia - Comprehensive polling data and election information',
            'scraper_file': 'scrapers/ballotpedia_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['ballotpedia'],
            'active': True
        },
        'apnorc': {
            'name': 'AP-NORC Center',
            'description': 'AP-NORC Center for Public Affairs Research - High-quality public opinion polling',
            'scraper_file': 'scrapers/apnorc_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['apnorc'],
            'active': True
        },
        'cbs': {
            'name': 'CBS News Poll',
            'description': 'CBS News polling and surveys',
            'scraper_file': 'scrapers/cbs_scraper.py',
            'base_url': POLLING_SITE_BASE_URLS['cbs'],
            'active': False
        }
    }
    
    @classmethod
    def get_base_url(cls, poll_id: str) -> Optional[str]:
        """Get base URL for a specific polling site"""
        return cls.POLLING_SITE_BASE_URLS.get(poll_id)
    
    @classmethod
    def get_active_polls(cls, research_topic: str = None):
        """Get only the polls that are currently implemented, with topic filtering"""
        active_polls = {k: v for k, v in cls.AVAILABLE_POLLS.items() if v['active']}
        
        # If research topic is provided, filter topic-specific polls
        if research_topic:
            topic_lower = research_topic.lower()
            
            # Check if topic is healthcare-related
            healthcare_terms = [
                'health', 'healthcare', 'medical', 'medicine', 'doctor', 'physician',
                'hospital', 'clinic', 'patient', 'treatment', 'therapy', 'drug',
                'medication', 'pharmacy', 'insurance', 'medicare', 'medicaid',
                'obamacare', 'aca', 'affordable care act', 'covid', 'coronavirus',
                'pandemic', 'vaccine', 'vaccination', 'mental health', 'depression',
                'anxiety', 'surgery', 'cancer', 'diabetes', 'heart disease',
                'prescription', 'copay', 'deductible', 'premium', 'coverage',
                'public health', 'epidemic', 'wellness', 'preventive care',
                'emergency room', 'urgent care', 'telehealth', 'telemedicine',
                'nursing', 'nurse', 'medical device', 'fda', 'cdc', 'nih', 'abortion'
            ]
            
            is_healthcare_topic = any(term in topic_lower for term in healthcare_terms)
            
            # If not healthcare-related, exclude KFF
            if not is_healthcare_topic and 'kff' in active_polls:
                active_polls = {k: v for k, v in active_polls.items() if k != 'kff'}
                logger.info(f"Filtered out KFF for non-healthcare topic: {research_topic}")
        
        return active_polls
    
    @classmethod
    def get_all_polls(cls):
        """Get all polls regardless of implementation status"""
        return cls.AVAILABLE_POLLS

class PollingScraper:
    """Handles multi-threaded polling site scraping"""
    
    def __init__(self, ui_instance=None, browser_tool=None):
        self.max_workers = 3
        self.timeout = 1000
        self.ui_instance = ui_instance
        self.browser_tool = browser_tool  # ADD: Browser tool for screenshots
        
        # Question deduplication tracking
        self.processed_questions = set()
        self.question_signatures = {}
        
        # ADD: Screenshot cache for polling sites
        self.polling_site_screenshots = {}
    
    async def _extract_questions_with_llm(self, content: str, url: str, survey_name: str, poll_name: str) -> List[str]:
        """Extract the original survey questions that were asked to respondents"""
        
        # Get LLM instance from the main app
        llm_instance = None
        if hasattr(self, 'ui_instance') and self.ui_instance:
            if hasattr(self.ui_instance, 'research_workflow'):
                llm_instance = self.ui_instance.research_workflow.llm
        
        if not llm_instance:
            print(f"⚠️ No LLM instance available for {poll_name}")
            return []
        
        # Limit content for faster processing
        content_sample = content[:4000] if len(content) > 4000 else content
        
        prompt = f"""Extract the ORIGINAL survey questions that were asked to respondents to generate this poll data.

    CONTENT: {content_sample}

    IMPORTANT: I want the actual questions that were asked to survey respondents, NOT questions about the poll results.

    RULES:
    1. Extract only the questions that were actually asked to survey participants
    2. Look for the questionnaire items that would generate the data shown
    3. DO NOT mention poll names or organizations in the questions
    4. Each question must end with "?"
    5. Maximum 8 questions
    6. If no original survey questions found, return "NO_QUESTIONS"

    FORMAT: One question per line, no numbering

    ORIGINAL SURVEY QUESTIONS:"""
        
        try:
            response = await llm_instance.ask(prompt, temperature=0.1)
            response_text = str(response).strip()
            
            if "NO_QUESTIONS" in response_text.upper():
                return []
            
            # Parse questions from response
            lines = response_text.split('\n')
            questions = []
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 15:
                    continue
                    
                # Remove numbering/bullets
                line = re.sub(r'^\d+[\.\)]\s*', '', line)
                line = re.sub(r'^[-•*]\s*', '', line)
                line = line.strip()
                
                # Skip if it looks like a question about poll results
                skip_phrases = [
                    'according to', 'poll shows', 'survey found', 'poll results',
                    'what is the current', 'who is in first', 'who is in second',
                    'how much support does', 'what percentage', 'poll indicates',
                    'emerson college', 'marist', 'quinnipiac', 'gallup'
                ]
                
                if any(phrase in line.lower() for phrase in skip_phrases):
                    print(f"⚠️ Skipping results-based question: {line}")
                    continue
                
                # Must be a proper question
                if line.endswith('?') and len(line) > 15 and len(line) < 300:
                    questions.append(line)
                    
                    if len(questions) >= 8:
                        break
            
            print(f"✅ LLM extracted {len(questions)} original survey questions")
            return questions
            
        except Exception as e:
            print(f"❌ LLM extraction failed: {e}")
            return []

    async def _capture_polling_site_screenshot(self, poll_id: str, poll_config: dict) -> Optional[str]:
        """Capture screenshot of polling site homepage"""
        if not self.browser_tool:
            logger.info(f"No browser tool available for {poll_config['name']} screenshot")
            return None
        
        # Check cache first
        if poll_id in self.polling_site_screenshots:
            logger.info(f"Using cached screenshot for {poll_config['name']}")
            return self.polling_site_screenshots[poll_id]
        
        try:
            # ENHANCED: Get base URL from centralized configuration
            base_url = PollingSiteConfig.get_base_url(poll_id)
            if not base_url:
                logger.warning(f"No base URL configured for {poll_id}")
                return None
            
            logger.info(f"📸 Capturing screenshot for {poll_config['name']} at {base_url}")
            
            # Capture screenshot using the existing capture_url_screenshot function
            screenshot_base64 = await capture_url_screenshot(base_url, self.browser_tool)
            
            if screenshot_base64:
                # ADDED: Validate the screenshot to detect security checks, errors, etc.
                is_valid = await self.validate_screenshot(screenshot_base64, base_url)
                if is_valid:
                    # Cache the screenshot
                    self.polling_site_screenshots[poll_id] = screenshot_base64
                    logger.info(f"✅ Screenshot captured and cached for {poll_config['name']}")
                    return screenshot_base64
                else:
                    logger.warning(f"⚠️ Invalid screenshot for {poll_config['name']} - likely security check or error page")
                    return None
            else:
                logger.warning(f"❌ No screenshot captured for {poll_config['name']}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error capturing screenshot for {poll_config['name']}: {e}")
            return None
    
    async def validate_screenshot(self, screenshot_base64: str, url: str) -> bool:
        """Simple screenshot validation"""
        try:
            if len(screenshot_base64) < 10000:
                return False
            
            image_data = base64.b64decode(screenshot_base64)
            if len(image_data) < 5000:
                return False
            
            data_sample = image_data[:1000]
            unique_bytes = len(set(data_sample))
            return unique_bytes >= 20
            
        except Exception:
            return False

    # ADD: Question deduplication methods
    def _create_question_signature(self, question: str) -> tuple:
        """Create a normalized signature for question deduplication"""
        # Normalize the question text
        normalized = re.sub(r'[^\w\s]', '', question.lower().strip())
        normalized = ' '.join(normalized.split())  # Remove extra whitespace
        
        # Create a hash for exact matches
        exact_hash = hashlib.md5(normalized.encode()).hexdigest()
        
        return exact_hash, normalized
    
    def _is_duplicate_question(self, question: str, threshold: float = 0.85) -> bool:
        """Check if question is a duplicate using both exact and similarity matching"""
        if not question or len(question.strip()) < 10:
            return True
            
        exact_hash, normalized = self._create_question_signature(question)
        
        # Check exact match first
        if exact_hash in self.processed_questions:
            return True
            
        # Check similarity with existing questions
        for existing_normalized in self.question_signatures.values():
            similarity = SequenceMatcher(None, normalized, existing_normalized).ratio()
            if similarity >= threshold:
                return True
        
        # Not a duplicate - store it
        self.processed_questions.add(exact_hash)
        self.question_signatures[exact_hash] = normalized
        return False

    async def scrape_selected_polls(self, selected_polls: list, research_topic: str, max_results_per_poll: int = 5):
        """Scrape multiple polling sites concurrently with screenshots"""
        
        if not selected_polls:
            return {
                'success': False,
                'message': 'No polling sites selected',
                'results': [],
                'polling_screenshots': []
            }
        
        # RESET deduplication tracking for each scraping session
        self.processed_questions = set()
        self.question_signatures = {}
        
        # Broadcast start status
        if self.ui_instance:
            await self.ui_instance.broadcast_scraping_status(
                "started", 
                f"Starting to scrape {len(selected_polls)} polling sites for '{research_topic}'"
            )

        logger.info(f"Starting concurrent scraping of {len(selected_polls)} polling sites for topic: {research_topic}")
        
        # STEP 1: Capture screenshots of polling sites (before scraping)
        polling_screenshots = []
        if self.browser_tool:
            logger.info("📸 Capturing polling site screenshots...")
            if self.ui_instance:
                await self.ui_instance.broadcast_scraping_status(
                    "progress", 
                    "Capturing screenshots of polling sites..."
                )
            
            # Capture screenshots for each selected poll
            screenshot_tasks = []
            for poll_id in selected_polls:
                if poll_id in PollingSiteConfig.get_active_polls():
                    poll_config = PollingSiteConfig.AVAILABLE_POLLS[poll_id]
                    screenshot_tasks.append(self._capture_polling_site_screenshot(poll_id, poll_config))
            
            # Run screenshot capture concurrently (with small delay between each)
            for i, screenshot_task in enumerate(screenshot_tasks):
                if i > 0:
                    await asyncio.sleep(2)  # Small delay between screenshot captures
                
                try:
                    screenshot_base64 = await screenshot_task
                    if screenshot_base64:
                        poll_id = selected_polls[i]
                        poll_config = PollingSiteConfig.AVAILABLE_POLLS[poll_id]
                        
                        # ENHANCED: Get base URL from centralized config
                        base_url = PollingSiteConfig.get_base_url(poll_id)
                        if not base_url:
                            logger.warning(f"No base URL found for {poll_id}")
                            continue
                        
                        polling_screenshots.append({
                            'poll_id': poll_id,
                            'poll_name': poll_config['name'],
                            'url': base_url,
                            'screenshot': screenshot_base64,
                            'title': f"Polling Site - {poll_config['name']}"
                        })
                        
                        logger.info(f"✅ Screenshot added for {poll_config['name']}")
                
                except Exception as e:
                    logger.error(f"Error in screenshot task: {e}")
        
        # STEP 2: Prepare and run scraping tasks
        scraping_tasks = []
        for i, poll_id in enumerate(selected_polls):
            if poll_id in PollingSiteConfig.get_active_polls():
                poll_config = PollingSiteConfig.AVAILABLE_POLLS[poll_id]
                scraping_tasks.append({
                    'poll_id': poll_id,
                    'poll_name': poll_config['name'],
                    'scraper_file': poll_config['scraper_file'],
                    'research_topic': research_topic,
                    'max_results': max_results_per_poll,
                    'delay': i * 3  # Stagger by 3 seconds to avoid server overload
                })
        
        if not scraping_tasks:
            return {
                'success': False,
                'message': 'No active polling sites selected',
                'results': [],
                'polling_screenshots': polling_screenshots
            }
        
        # STEP 3: Run scrapers concurrently
        results = await self._run_scrapers_concurrent_fixed(scraping_tasks)
        
        # STEP 4: Broadcast completion status
        if self.ui_instance:
            unique_questions = sum(len(r.get('unique_questions', [])) for r in results)
            total_raw_questions = sum(len(r.get('raw_questions', [])) for r in results)
            duplicates_removed = total_raw_questions - unique_questions
            
            status_msg = f"Scraping completed. Found {unique_questions} unique questions"
            if duplicates_removed > 0:
                status_msg += f" ({duplicates_removed} duplicates removed)"
            status_msg += f" from {len([r for r in results if r['success']])} successful polls"
            
            # Add screenshot info
            if polling_screenshots:
                status_msg += f". Captured {len(polling_screenshots)} polling site screenshots"
            
            await self.ui_instance.broadcast_scraping_status("completed", status_msg)

        # STEP 5: Process and format results
        formatted_results = self._process_scraping_results(results)
        
        # ADD: Include polling screenshots in results
        formatted_results['polling_screenshots'] = polling_screenshots
        formatted_results['polling_screenshots_count'] = len(polling_screenshots)
        
        logger.info(f"Completed scraping. Total unique questions found: {len(formatted_results.get('all_questions', []))}")
        logger.info(f"Polling site screenshots captured: {len(polling_screenshots)}")
        
        return formatted_results
    
    async def _run_scrapers_concurrent_fixed(self, scraping_tasks):
        """FIXED: Run multiple scrapers concurrently with proper asyncio control"""
        results = []
        total_tasks = len(scraping_tasks)
        completed_tasks = 0
        
        # Broadcast initial progress
        if self.ui_instance:
            await self.ui_instance.broadcast_scraping_status(
                "progress", 
                f"Starting concurrent scraping of {total_tasks} polling sites..."
            )
        
        # FIXED: Use asyncio semaphore for better concurrency control
        semaphore = asyncio.Semaphore(self.max_workers)
        
        async def run_single_scraper_async(task):
            async with semaphore:
                # Apply staggered delay
                if task['delay'] > 0:
                    await asyncio.sleep(task['delay'])
                
                # Run scraper in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None, 
                    self._run_single_scraper, 
                    task
                )
        
        # Start all scrapers concurrently
        tasks = [run_single_scraper_async(task) for task in scraping_tasks]
        
        # Process results as they complete
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                results.append(result)
                completed_tasks += 1
                
                # Broadcast progress update
                if self.ui_instance:
                    status_detail = f"Completed {result['poll_name']} ({completed_tasks}/{total_tasks})"
                    if result['success']:
                        unique_count = len(result.get('unique_questions', []))
                        raw_count = len(result.get('raw_questions', []))
                        duplicates = raw_count - unique_count
                        status_detail += f" - Found {unique_count} unique questions"
                        if duplicates > 0:
                            status_detail += f" ({duplicates} duplicates filtered)"
                    else:
                        status_detail += f" - Failed: {result['error'][:50]}..."
                    
                    await self.ui_instance.broadcast_scraping_status("progress", status_detail)

                # Log progress
                logger.info(f"✅ Completed scraping {result['poll_name']} ({completed_tasks}/{total_tasks})")
                
                if result['success']:
                    unique_count = len(result.get('unique_questions', []))
                    logger.info(f"   Found {unique_count} unique questions")
                else:
                    logger.warning(f"   Failed: {result['error']}")
                        
            except Exception as e:
                completed_tasks += 1
                error_result = {
                    'poll_id': 'unknown',
                    'poll_name': 'Unknown',
                    'success': False,
                    'error': str(e),
                    'raw_questions': [],
                    'unique_questions': [],
                    'source_info': {}
                }
                results.append(error_result)
                
                # Broadcast error
                if self.ui_instance:
                    await self.ui_instance.broadcast_scraping_status(
                        "progress", 
                        f"Failed task ({completed_tasks}/{total_tasks}): {str(e)[:50]}..."
                    )

                logger.error(f"❌ Failed scraping task: {e}")
        
        logger.info(f"Completed all scraping tasks. Total questions found: {sum(len(r.get('unique_questions', [])) for r in results)}")
        return results
    
    def _run_single_scraper(self, task):
        """FIXED: Run a single scraper with better timeout handling"""
        try:
            poll_id = task['poll_id']
            poll_name = task['poll_name']
            scraper_file = task['scraper_file']
            research_topic = task['research_topic']
            max_results = task['max_results']
            
            logger.info(f"🔍 Starting scraper for {poll_name}")
            
            # Create a temporary file to store results
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as temp_file:
                temp_filepath = temp_file.name
            
            try:
                # Run the scraper as a subprocess
                cmd = [
                    'python', scraper_file,
                    '--keyword', research_topic,
                    '--max-results', str(max_results),
                    '--output', temp_filepath,
                    '--headless', 'true'
                ]
                
                # FIXED: Use Popen for better timeout control
                process = subprocess.Popen(
                    cmd, 
                    stdout=None,
                    stderr=None,
                    text=True, 
                    cwd=os.path.dirname(os.path.abspath(__file__))
                )
                
                # Wait with timeout
                try:
                    stdout, stderr = process.communicate(timeout=self.timeout)
                    return_code = process.returncode
                except subprocess.TimeoutExpired:
                    logger.warning(f"⏰ Killing timed out scraper for {poll_name}")
                    process.kill()
                    stdout, stderr = process.communicate()
                    return_code = -1
                
                if return_code == 0:
                    # Read results from temp file
                    with open(temp_filepath, 'r', encoding='utf-8') as f:
                        scraper_results = json.load(f)
                    
                    # FIXED: Process the results with deduplication - MAKE IT SYNC
                    processed_results = self._process_single_scraper_results_with_dedup_sync(
                        poll_id, poll_name, scraper_results
                    )
                    
                    return processed_results
                else:
                    logger.error(f"Scraper process failed for {poll_name}: {stderr}")
                    return {
                        'poll_id': poll_id,
                        'poll_name': poll_name,
                        'success': False,
                        'error': f"Scraper process failed: {stderr[:200]}",
                        'raw_questions': [],
                        'unique_questions': [],
                        'source_info': {}
                    }
                    
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_filepath)
                except:
                    pass
                    
        except subprocess.TimeoutExpired:
            logger.error(f"Scraper timeout for {poll_name}")
            return {
                'poll_id': poll_id,
                'poll_name': poll_name,
                'success': False,
                'error': f"Scraper timed out after {self.timeout} seconds",
                'raw_questions': [],
                'unique_questions': [],
                'source_info': {}
            }
        except Exception as e:
            logger.error(f"Error running scraper for {poll_name}: {e}")
            return {
                'poll_id': poll_id,
                'poll_name': poll_name,
                'success': False,
                'error': str(e),
                'raw_questions': [],
                'unique_questions': [],
                'source_info': {}
            }

    def _process_single_scraper_results_with_dedup_sync(self, poll_id, poll_name, scraper_results):
        """Process results and extract questions using LLM (except Marquette)"""
        try:
            raw_questions = []
            unique_questions = []
            
            if 'surveys' not in scraper_results:
                return self._create_error_result(poll_id, poll_name, "No surveys in results")
            
            for survey in scraper_results['surveys']:
                survey_name = survey.get('survey_code', f"{poll_name} Survey")
                survey_date = survey.get('survey_date', 'Unknown Date')
                survey_question = survey.get('survey_question', '')
                survey_url = survey.get('url', '')
                embedded_content = survey.get('embedded_content', '')
                
                if not embedded_content:
                    continue
                
                extracted_questions = []
                
                # STEP 1: Check if questions are pre-extracted (Marquette case)
                if 'extracted_questions' in survey and survey['extracted_questions']:
                    print(f"✅ Using pre-extracted questions from {poll_name}")
                    extracted_questions = survey['extracted_questions']
                
                # STEP 2: Use LLM extraction for all other polls
                else:
                    print(f"🤖 Using LLM extraction for {poll_name}")
                    # Run LLM extraction synchronously
                    import asyncio
                    
                    try:
                        # Create new event loop if needed
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        
                        # Run LLM extraction
                        extracted_questions = loop.run_until_complete(
                            self._extract_questions_with_llm(
                                embedded_content, survey_url, survey_name, poll_name
                            )
                        )
                        
                    except Exception as e:
                        print(f"❌ LLM extraction failed for {poll_name}: {e}")
                        extracted_questions = []
                
                # STEP 3: Process extracted questions with deduplication
                for question in extracted_questions:
                    raw_questions.append(question)
                    
                    # Apply deduplication
                    if not self._is_duplicate_question(question):
                        unique_questions.append({
                            'question': question,
                            'source': survey_url,
                            'survey_name': survey_name,
                            'survey_date': survey_date,
                            'survey_question': survey_question,
                            'poll_id': poll_id,
                            'poll_name': poll_name,
                            'extraction_method': 'llm_extraction' if poll_id != 'marquette' else 'regex_extraction'
                        })
            
            print(f"✅ Processed {len(unique_questions)} unique questions from {poll_name}")
            
            return {
                'poll_id': poll_id,
                'poll_name': poll_name,
                'success': True,
                'raw_questions': raw_questions,
                'unique_questions': unique_questions,
                'source_info': {
                    'total_surveys': len(scraper_results.get('surveys', [])),
                    'raw_questions_count': len(raw_questions),
                    'unique_questions_count': len(unique_questions),
                    'duplicates_filtered': len(raw_questions) - len(unique_questions),
                    'scraping_date': scraper_results.get('scraped_at', time.strftime('%Y-%m-%d %H:%M:%S'))
                }
            }
            
        except Exception as e:
            print(f"❌ Error processing results for {poll_name}: {e}")
            return self._create_error_result(poll_id, poll_name, str(e))

    def _create_error_result(self, poll_id, poll_name, error_message):
        """Create error result structure"""
        return {
            'poll_id': poll_id,
            'poll_name': poll_name,
            'success': False,
            'error': error_message,
            'raw_questions': [],
            'unique_questions': [],
            'source_info': {}
        }
        
    def _process_scraping_results(self, results):
        """FIXED: Process and combine results from all scrapers with deduplication info"""
        all_questions = []
        successful_polls = []
        failed_polls = []
        total_raw_questions = 0
        total_duplicates_removed = 0
        
        for result in results:
            if result['success']:
                unique_count = len(result['unique_questions'])
                raw_count = len(result.get('raw_questions', []))
                duplicates = raw_count - unique_count
                
                successful_polls.append({
                    'poll_id': result['poll_id'],
                    'poll_name': result['poll_name'],
                    'unique_question_count': unique_count,
                    'raw_question_count': raw_count,
                    'duplicates_filtered': duplicates,
                    'source_info': result['source_info']
                })
                
                all_questions.extend(result['unique_questions'])
                total_raw_questions += raw_count
                total_duplicates_removed += duplicates
            else:
                failed_polls.append({
                    'poll_id': result['poll_id'],
                    'poll_name': result['poll_name'],
                    'error': result['error']
                })
        
        return {
            'success': len(successful_polls) > 0,
            'message': f"Scraped {len(successful_polls)} polls successfully, {len(failed_polls)} failed. "
                      f"Found {len(all_questions)} unique questions ({total_duplicates_removed} duplicates removed)",
            'all_questions': all_questions,
            'successful_polls': successful_polls,
            'failed_polls': failed_polls,
            'total_unique_questions': len(all_questions),
            'total_raw_questions': total_raw_questions,
            'total_duplicates_removed': total_duplicates_removed
        }

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
    research_motivation: Optional[str] = None  # NEW FIELD
    target_population: Optional[str] = None
    timeframe: Optional[str] = None
    questions: Optional[List[str]] = None
    internet_questions: Optional[List[str]] = None
    internet_sources: Optional[List[str]] = None
    screenshots: List[Dict] = None
    use_internet_questions: bool = False
    stage: ResearchStage = ResearchStage.INITIAL
    user_responses: Optional[Dict] = None
    questionnaire_responses: Optional[Dict] = None
    chat_history: Optional[List[Dict]] = None
    research_screenshots: List[Dict] = None
    
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

    # ADDED: Poll selection fields
    available_polls: Optional[Dict] = None
    selected_polls: Optional[List[str]] = None
    show_poll_selection: bool = False
    awaiting_poll_selection: bool = False

class UserMessage(BaseModel):
    content: str
    action_type: Optional[str] = None
    research_session_id: Optional[str] = None

class URLProcessor:
    """Unified URL processor that scrapes content once and validates everything simultaneously"""
    
    def __init__(self, llm_instance, browser_tool=None):
        self.llm = llm_instance
        self.browser_tool = browser_tool
        self.question_extractor = ImprovedQuestionExtractor()
        # Cache to store scraped content and avoid re-scraping
        self.content_cache = {}
        self.screenshot_cache = {}
        # NEW: Track processed URLs to avoid overlap between research and internet search
        self.processed_research_urls = set()
        self.processed_internet_urls = set()
    
    def mark_research_url_processed(self, url: str):
        """Mark a URL as processed during research phase"""
        self.processed_research_urls.add(url)
    
    def mark_internet_url_processed(self, url: str):
        """Mark a URL as processed during internet search phase"""
        self.processed_internet_urls.add(url)
    
    def is_url_already_processed_for_research(self, url: str) -> bool:
        """Check if URL was already processed in research phase"""
        return url in self.processed_research_urls
    
    def is_url_already_processed_for_internet(self, url: str) -> bool:
        """Check if URL was already processed in internet search phase"""
        return url in self.processed_internet_urls
    
    async def process_urls_for_research(self, urls: List[str], research_topic: str, target_count: int = 1) -> Dict:
        """Process URLs for research summaries - mark as research URLs"""
        research_summaries = []
        screenshots = []
        processed_urls = []
        
        for i, url in enumerate(urls):
            if len(research_summaries) >= target_count:
                break
                
            # Mark as research URL
            self.mark_research_url_processed(url)
            logger.info(f"Processing RESEARCH URL {i+1}/{len(urls)}: {url}")
            
            try:
                # Step 1: Check if URL is valid and deep
                if not self._is_valid_url(url) or not self._is_deep_url(url):
                    logger.info(f"❌ URL validation failed: {url}")
                    continue
                
                # Step 2: Scrape content once (check cache first)
                content = await self._get_or_scrape_content(url)
                if not content or len(content) < 300:
                    logger.info(f"❌ Insufficient content: {url}")
                    continue
                
                # Step 3: Validate content relevance using LLM
                is_relevant = await self._validate_content_relevance(content, research_topic, url)
                if not is_relevant:
                    logger.info(f"❌ Content not relevant to topic: {url}")
                    continue
                
                # Step 4: Content is valid - store it and create summary
                self.content_cache[url] = content
                summary = await self._create_individual_research_summary(content, url, research_topic)
                
                if summary:
                    research_summaries.append({
                        'url': url,
                        'summary': summary,
                        'domain': self._extract_domain(url),
                        'content': content  # Store content for potential reuse
                    })
                    processed_urls.append(url)
                    
                    # Step 5: Take screenshot since content is valid
                    screenshot = await self._get_or_capture_screenshot(url)
                    if screenshot:
                        screenshots.append({
                            'url': url,
                            'screenshot': screenshot,
                            'title': f"Research Study - {self._extract_domain(url)}"
                        })
                        logger.info(f"✅ RESEARCH URL processed successfully: {url}")
                    
            except Exception as e:
                logger.error(f"Error processing research URL {url}: {e}")
                continue
        
        return {
            'research_summaries': research_summaries,
            'screenshots': screenshots,
            'processed_urls': processed_urls,
            'cached_content': {url: self.content_cache[url] for url in processed_urls}
        }
    
    async def process_urls_for_questions(self, urls: List[str], research_topic: str, target_population: str, target_count: int = 6) -> Dict:
        """Process URLs for question extraction - mark as internet URLs and avoid research URLs"""
        extracted_questions = []
        screenshots = []
        processed_urls = []
        seen_questions = set()
        
        for i, url in enumerate(urls):
            if len(processed_urls) >= target_count:
                break
            
            # IMPORTANT: Skip if this URL was already processed for research
            if self.is_url_already_processed_for_research(url):
                logger.info(f"⏭️ Skipping {url} - already processed for research")
                continue
                
            # Mark as internet search URL
            self.mark_internet_url_processed(url)
            logger.info(f"Processing INTERNET SEARCH URL {i+1}/{len(urls)}: {url}")
            
            try:
                # Step 1: Check if URL is valid and deep
                if not self._is_valid_url(url) or not self._is_deep_url(url):
                    logger.info(f"❌ URL validation failed: {url}")
                    continue
                
                # Step 2: Scrape content once (check cache first)
                content = await self._get_or_scrape_content(url)
                if not content or len(content) < 200:
                    logger.info(f"❌ Insufficient content: {url}")
                    continue
                
                # Step 3: Validate content relevance using LLM
                is_relevant = await self._validate_content_relevance(content, research_topic, url)
                if not is_relevant:
                    logger.info(f"❌ Content not relevant to topic: {url}")
                    continue
                
                # Step 4: Content is valid - store it and extract questions
                self.content_cache[url] = content
                url_questions = await self._extract_questions_from_content(content, url)
                
                # Filter unique questions
                unique_questions = []
                for q_dict in url_questions:
                    question_text = q_dict['question'].lower().strip()
                    if question_text not in seen_questions and len(question_text) > 15:
                        seen_questions.add(question_text)
                        unique_questions.append(q_dict)
                
                if unique_questions:
                    extracted_questions.extend(unique_questions)
                    processed_urls.append(url)
                    
                    # Step 5: Take screenshot since content is valid
                    screenshot = await self._get_or_capture_screenshot(url)
                    if screenshot:
                        screenshots.append({
                            'url': url,
                            'screenshot': screenshot,
                            'title': f"Survey Research - {self._extract_domain(url)}"
                        })
                        
                    logger.info(f"✅ Found {len(unique_questions)} unique questions from INTERNET SEARCH: {url}")
                else:
                    logger.info(f"⚠️ No unique questions found in: {url}")
                    
            except Exception as e:
                logger.error(f"Error processing internet search URL {url}: {e}")
                continue
        
        return {
            'extracted_questions': extracted_questions,
            'screenshots': screenshots,
            'processed_urls': processed_urls,
            'cached_content': {url: self.content_cache[url] for url in processed_urls}
        }
    
    async def _get_or_scrape_content(self, url: str) -> str:
        """Get content from cache or scrape it once"""
        if url in self.content_cache:
            logger.info(f"📋 Using cached content for: {url}")
            return self.content_cache[url]
        
        logger.info(f"🔍 Scraping new content for: {url}")
        content = await self._scrape_page_content(url)
        if content:
            self.content_cache[url] = content
        return content
    
    async def _get_or_capture_screenshot(self, url: str) -> Optional[str]:
        """Get screenshot from cache or capture it once"""
        if url in self.screenshot_cache:
            logger.info(f"📸 Using cached screenshot for: {url}")
            return self.screenshot_cache[url]
        
        if self.browser_tool:
            logger.info(f"📸 Capturing new screenshot for: {url}")
            screenshot = await capture_url_screenshot(url, self.browser_tool)
            if screenshot:
                is_valid = await self.validate_screenshot(screenshot, url)
                if is_valid:
                    self.screenshot_cache[url] = screenshot
                    return screenshot
        return None
    
    async def _validate_content_relevance(self, content: str, research_topic: str, url: str) -> bool:
        """Use LLM to determine if content is related to research topic"""
        content_sample = content[:2000]  # Limit for efficiency
        
        prompt = f"""
        Determine if this webpage content is related to the research topic "{research_topic}".
        
        Content sample from {url}:
        {content_sample}
        
        Respond with ONLY "YES" if the content is clearly related to "{research_topic}" research, studies, or surveys.
        Respond with ONLY "NO" if the content is not related.
        
        Response:
        """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.1)
            cleaned_response = remove_chinese_and_punct(str(response)).strip().upper()
            return "YES" in cleaned_response
        except Exception as e:
            logger.error(f"Error checking content relevance for {url}: {e}")
            return False
    
    async def _extract_questions_from_content(self, content: str, url: str) -> List[Dict]:
        """Extract questions from already scraped content with LLM fallback"""
        
        # Initialize enhanced extractor if not exists
        if not hasattr(self, '_enhanced_extractor'):
            from question_extractor import QuestionExtractor
            self._enhanced_extractor = QuestionExtractor(self.llm)
        
        try:
            # Use enhanced extraction with LLM fallback
            questions = await self._enhanced_extractor.extract_questions_with_metadata(content, url)
            logger.info(f"Enhanced extraction: {len(questions)} questions from {url}")
            return questions
            
        except Exception as e:
            logger.error(f"Enhanced extraction failed for {url}: {e}")
            
            # Fallback to pattern-based extraction
            try:
                from question_extractor import extract_questions_from_content
                pattern_questions = extract_questions_from_content(content)
                
                # Convert to expected format
                question_dicts = []
                for i, question in enumerate(pattern_questions):
                    question_dicts.append({
                        'question': question,
                        'source': url,
                        'extraction_method': 'pattern_fallback',
                        'question_number': i + 1
                    })
                
                logger.info(f"Pattern fallback: {len(question_dicts)} questions from {url}")
                return question_dicts
                
            except Exception as fallback_error:
                logger.error(f"All extraction methods failed for {url}: {fallback_error}")
                return []
    
    async def _llm_extract_questions(self, content: str, url: str) -> List[Dict]:
        """Extract questions using LLM from already scraped content"""
        content_sample = content[:3000]
        
        prompt = f"""
        Extract EXISTING survey questions from this webpage content. Find questions that already exist - do NOT create new ones.

        WEBPAGE: {url}
        CONTENT: {content_sample}

        EXTRACTION RULES:
        1. Only extract questions that already exist in the content
        2. Questions must end with "?"
        3. Questions should be 20-200 characters long
        4. Return maximum 6 questions
        5. Format: One question per line, no numbering
        6. If no actual questions found, return "NO_QUESTIONS_FOUND"

        EXISTING QUESTIONS:
        """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.1)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            if "NO_QUESTIONS_FOUND" in cleaned_response.upper():
                return []
            
            lines = cleaned_response.split('\n')
            questions_found = []
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 20:
                    continue
                
                # Clean up formatting
                line = re.sub(r'^\d+[\.\)]\s*', '', line)
                line = re.sub(r'^[-•*]\s*', '', line)
                line = line.strip()
                
                if line.endswith('?') and len(line) > 20 and len(line) < 250:
                    questions_found.append({
                        'question': line,
                        'source': url,
                        'extraction_method': 'llm_extraction'
                    })
                    
                    if len(questions_found) >= 6:
                        break
            
            return questions_found
            
        except Exception as e:
            logger.error(f"LLM extraction error for {url}: {e}")
            return []
    
    async def _create_individual_research_summary(self, content: str, url: str, research_topic: str) -> str:
        """Create summary from already scraped content"""
        content_sample = content[:4000]
        
        prompt = f"""
        Create a concise one-sentence summary of this research study related to "{research_topic}".
        
        Research URL: {url}
        Content: {content_sample}
        
        Requirements:
        - EXACTLY one sentence (maximum 20 words)
        - Focus ONLY on the main finding or conclusion
        - Do NOT mention methodology, sample size, or participants
        - Be specific about what was discovered or concluded
        
        Summary:
        """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.3)
            summary = remove_chinese_and_punct(str(response)).strip()
            
            # Clean up and ensure it's a single sentence
            summary = summary.split('.')[0]
            if summary:
                summary = summary.strip()
                if not summary.endswith('.'):
                    summary += '.'
            
            # Limit to 20 words maximum
            words = summary.split()
            if len(words) > 20:
                summary = ' '.join(words[:20]) + '.'
                
            return summary if summary else "Research study with relevant findings."
            
        except Exception as e:
            logger.error(f"Error creating research summary for {url}: {e}")
            return "Research study with relevant findings."
    
    def _is_valid_url(self, url: str) -> bool:
        """Enhanced URL validation"""
        try:
            problematic_patterns = [
                'accounts.google.com', 'login.', 'signin.', 'auth.', 'captcha',
                '.pdf', '.doc', '.zip', 'javascript:', 'mailto:', 'tel:', 'ftp:'
            ]
            
            url_lower = url.lower()
            for pattern in problematic_patterns:
                if pattern in url_lower:
                    return False
            
            if not url.startswith(('http://', 'https://')):
                return False
            
            if len(url) > 500:
                return False
            
            return True
            
        except Exception:
            return False
    
    def _is_deep_url(self, url: str) -> bool:
        """Check if URL is a deep URL (not just root domain)"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            
            if not path or len(path) < 3:
                return False
            
            path_segments = [seg for seg in path.split('/') if seg and seg.strip()]
            if len(path_segments) < 1:
                return False
            
            # Check for content indicators
            content_indicators = [
                'survey', 'research', 'study', 'questionnaire', 'poll',
                'article', 'blog', 'post', 'report', 'analysis'
            ]
            
            first_segment_lower = path_segments[0].lower()
            for indicator in content_indicators:
                if indicator in first_segment_lower:
                    return True
            
            return len(path_segments) >= 2 or len(path) >= 15
            
        except Exception:
            return False
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc
        except:
            return "Unknown"
    
    async def _scrape_page_content(self, url: str) -> str:
        """Scrape page content (same as existing implementation)"""
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
            
            if not main_content:
                main_content = soup.get_text()
            
            # Clean up text
            lines = (line.strip() for line in main_content.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            cleaned_text = ' '.join(chunk for chunk in chunks if chunk)
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
            
            return cleaned_text[:12000]  # Limit to 12K characters
            
        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return ""
    
    async def validate_screenshot(self, screenshot_base64: str, url: str) -> bool:
        """Simple screenshot validation"""
        try:
            if len(screenshot_base64) < 10000:
                return False
            
            image_data = base64.b64decode(screenshot_base64)
            if len(image_data) < 5000:
                return False
            
            data_sample = image_data[:1000]
            unique_bytes = len(set(data_sample))
            return unique_bytes >= 20
            
        except Exception:
            return False

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
    def __init__(self, llm_instance, ui_instance=None):
        self.llm = llm_instance
        self.active_sessions: Dict[str, ResearchDesign] = {}
        self.browser_tool = None
        self.ui_instance = ui_instance
        
        # Initialize URL processor for optimized processing
        self._url_processor = None
        
        # Google Custom Search API configuration
        self.google_api_key = os.getenv('GOOGLE_API_KEY')
        self.google_cse_id = os.getenv('GOOGLE_CSE_ID')
        
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

    def _get_url_processor(self):
        """Get or create URL processor instance"""
        if self._url_processor is None:
            self._url_processor = URLProcessor(self.llm, self.browser_tool)
        return self._url_processor

    async def _collect_all_urls(self, research_topic: str) -> List[str]:
        """Collect 30 unique deep URLs for INTERNET SEARCH - FIXED to exclude research URLs"""
        try:
            if not self.search_service:
                logger.warning("Google Custom Search API not available")
                return []
            
            # Get URL processor to check for research URLs
            url_processor = self._get_url_processor()
            
            # INTERNET SEARCH-SPECIFIC search query (different from research)
            search_query = f"survey questionnaire questions about {research_topic}"
            logger.info(f"Collecting INTERNET SEARCH URLs for: {search_query}")
            
            all_unique_urls = []
            seen_urls = set()
            
            # INTERNET SEARCH-SPECIFIC search variations (completely different from research)
            search_variations = [
                f"survey questionnaire questions about {research_topic}",
                f"{research_topic} survey instrument questions",
                f"{research_topic} questionnaire examples forms",
                f"{research_topic} poll questions survey tools"
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
                                # CRITICAL CHECK: Skip if this URL was already processed for research
                                if url_processor.is_url_already_processed_for_research(link):
                                    logger.info(f"⏭️ Skipping research URL: {link}")
                                    continue
                                
                                # Check if it's a valid deep URL
                                if self._is_valid_url(link):
                                    all_unique_urls.append(link)
                                    seen_urls.add(link)
                                    logger.info(f"✅ Collected INTERNET SEARCH URL #{len(all_unique_urls)}: {title}")
                                    
                                    if len(all_unique_urls) >= 30:
                                        break
                                else:
                                    logger.info(f"❌ Filtered out: {title} - {link}")
                    
                    # Small delay between searches
                    await asyncio.sleep(1)
                    
                except Exception as api_error:
                    logger.error(f"Internet search API error for '{search_term}': {api_error}")
                    continue
            
            logger.info(f"INTERNET SEARCH URL collection results:")
            logger.info(f"  - Total unique deep URLs collected: {len(all_unique_urls)}")
            logger.info(f"  - Target was: 30 URLs")
            logger.info(f"  - Research URLs excluded from collection")
            
            return all_unique_urls[:30]  # Ensure we don't exceed 30
            
        except Exception as e:
            logger.error(f"Error collecting internet search URLs: {e}")
            return []

    async def _show_poll_selection(self, session: ResearchDesign, research_topic) -> str:
        active_polls = PollingSiteConfig.get_active_polls(session.research_topic)
        
        if not active_polls:
            return """❌ **No Polling Sites Available**
    No polling site scrapers are currently implemented. Please check back later."""
        
        # Store poll data and flags for frontend/UI
        session.__dict__['available_polls'] = active_polls
        session.__dict__['show_poll_selection'] = True
        session.__dict__['awaiting_poll_selection'] = True

        polls_list = []
        for poll_id, poll_info in active_polls.items():
            polls_list.append(f"• **{poll_info['name']}** - {poll_info['description']}")
        
        return f"""🗳️ **Select Polling Sites to Search**

    Choose which polling organizations you'd like to search for questions about "{session.research_topic}":

    **Available Polling Sites ({len(active_polls)}):**
    {chr(10).join(polls_list)}

    Use the poll selection interface to choose your sources, then click **Start Polling Search**.

    **Note:** Multiple polls will be scraped simultaneously to save time."""

    async def _extract_actual_questions_from_content(self, scraped_content: str, url: str) -> List[Dict]:
        """Extract actual survey questions with improved error handling, source tracking, and LLM fallback"""
        
        # Initialize the improved extractor WITH LLM instance
        if not hasattr(self, '_question_extractor'):
            from question_extractor import QuestionExtractor  # Import the enhanced class
            self._question_extractor = QuestionExtractor(self.llm)  # Pass LLM instance
        
        try:
            # Use ASYNC extraction with LLM fallback
            found_questions = await self._question_extractor.extract_questions_with_metadata(
                scraped_content, url, ""
            )
            
            logger.info(f"✅ Enhanced extraction found {len(found_questions)} questions from {url}")
            return found_questions
            
        except Exception as e:
            logger.error(f"❌ Error in enhanced question extraction from {url}: {e}")
            
            # Fallback to old pattern-based method
            try:
                from question_extractor import extract_questions_from_content
                pattern_questions = extract_questions_from_content(scraped_content)
                
                # Convert to expected format
                question_dicts = []
                for i, question in enumerate(pattern_questions):
                    question_dicts.append({
                        'question': question,
                        'source': url,
                        'extraction_method': 'pattern_fallback',
                        'question_number': i + 1
                    })
                
                logger.info(f"⚠️ Used pattern fallback: {len(question_dicts)} questions")
                return question_dicts
                
            except Exception as fallback_error:
                logger.error(f"❌ Pattern fallback also failed: {fallback_error}")
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
        """Search selected polling sites for questions WITH SCREENSHOTS"""
        
        # Check if poll selection was made
        selected_polls = session.__dict__.get('selected_polls', [])
        logger.info(f"🔍 DEBUG: _search_internet_for_questions called with selected_polls: {selected_polls}")
        
        if not selected_polls:
            logger.info("🔍 DEBUG: No polls selected, setting poll selection flags")
            # Set poll selection flags and return special indicator
            session.__dict__['awaiting_poll_selection'] = True
            session.__dict__['show_poll_selection'] = True
            session.__dict__['available_polls'] = PollingSiteConfig.get_active_polls()
            logger.info(f"🔍 DEBUG: Set flags - awaiting_poll_selection: {session.__dict__.get('awaiting_poll_selection')}, show_poll_selection: {session.__dict__.get('show_poll_selection')}")
            # Return a special tuple to indicate poll selection needed
            return None, None, None
        
        # FIX: Initialize session question pools early
        if session.selected_questions_pool is None:
            session.selected_questions_pool = []
            logger.info("Initialized selected_questions_pool to empty list")
        
        if session.user_selected_questions is None:
            session.user_selected_questions = []
            logger.info("Initialized user_selected_questions to empty list")
        
        # Initialize polling scraper WITH UI instance AND browser tool for screenshots
        polling_scraper = PollingScraper(ui_instance=self.ui_instance, browser_tool=self.browser_tool)
        
        try:
            # Scrape selected polls concurrently WITH SCREENSHOTS
            scraping_results = await polling_scraper.scrape_selected_polls(
                selected_polls, research_topic, max_results_per_poll=5
            )
            
            if not scraping_results['success']:
                logger.warning("Polling scraper returned unsuccessful result")
                return [], [], []
            
            # Format questions for UI
            formatted_questions = []
            for question_data in scraping_results['all_questions']:
                formatted_questions.append({
                    'question': question_data['question'],
                    'source': f"{question_data['source']} - {question_data['survey_name']}",
                    'poll_id': question_data['poll_id'],
                    'survey_name': question_data['survey_name'],
                    'survey_date': question_data['survey_date'],
                    'extraction_method': question_data['extraction_method']
                })
            
            # Create source list
            sources = list(set([q['source'] for q in formatted_questions]))
            
            # GET POLLING SITE SCREENSHOTS from scraping results
            polling_screenshots = scraping_results.get('polling_screenshots', [])
            
            # Convert polling screenshots to the format expected by the UI
            screenshots = []
            for poll_screenshot in polling_screenshots:
                screenshots.append({
                    'url': poll_screenshot['url'],
                    'screenshot': poll_screenshot['screenshot'],
                    'title': poll_screenshot['title']
                })
            
            logger.info(f"✅ Polling search complete: {len(formatted_questions)} questions, {len(screenshots)} polling site screenshots")
            
            # FIX: Ensure we always return valid lists (not None)
            return formatted_questions or [], sources or [], screenshots or []
            
        except Exception as e:
            logger.error(f"Error in polling search: {e}")
            # FIX: Always return valid empty lists instead of None
            return [], [], []   


    # Add this method to handle poll selection input
    async def _handle_poll_selection(self, session_id: str, selected_polls: List[str]) -> str:
        """Handle poll selection from user - FIXED to properly store selected questions"""
        session = self.active_sessions[session_id]
        
        if not selected_polls:
            return """❌ **No Polls Selected**
    Please select at least one polling site to search."""
        
        # Store selected polls
        session.__dict__['selected_polls'] = selected_polls
        session.__dict__['awaiting_poll_selection'] = False
        session.__dict__['show_poll_selection'] = False
        
        # Get poll names for display
        active_polls = PollingSiteConfig.get_active_polls()
        selected_names = [active_polls[poll_id]['name'] for poll_id in selected_polls if poll_id in active_polls]
        
        # Now start the actual search WITH SCREENSHOTS
        extracted_questions, sources, screenshots = await self._search_internet_for_questions(
            session.research_topic, session.target_population, session
        )
        
        if not extracted_questions:
            return f"""❌ **No Questions Found**
    Unable to find survey questions from the selected polling sites."""
        
        # CRITICAL FIX: Initialize all question tracking properly
        if session.selected_questions_pool is None:
            session.selected_questions_pool = []
        if session.user_selected_questions is None:
            session.user_selected_questions = []
        
        # FIXED: Store extracted questions in ALL the right places
        session.selected_questions_pool = extracted_questions
        session.internet_questions = [q['question'] for q in extracted_questions]
        session.internet_sources = sources
        session.extracted_questions_with_sources = extracted_questions
        
        # IMPORTANT: Set flags to use these questions
        session.use_internet_questions = True
        
        # Handle screenshots properly
        if screenshots:
            if session.screenshots is None:
                session.screenshots = []
            
            # Preserve existing research screenshots and add polling screenshots
            research_screenshots = getattr(session, 'research_screenshots', None) or []
            combined_screenshots = []
            
            if research_screenshots:
                combined_screenshots.extend(research_screenshots)
            combined_screenshots.extend(screenshots)
            
            session.screenshots = combined_screenshots
            session.__dict__['polling_site_screenshots'] = screenshots
            session.__dict__['polling_screenshots_count'] = len(screenshots)
        
        # Move to selection stage
        session.stage = ResearchStage.DECISION_POINT
        session.awaiting_selection = True
        
        # Format questions for UI selection
        ui_selection_data = self._format_questions_for_ui_selection(extracted_questions)
        session.__dict__['ui_selection_data'] = ui_selection_data
        session.__dict__['trigger_question_selection_ui'] = True
        session.__dict__['show_question_selection'] = True
        
        return f"""🎯 **Questions Found from Polling Sites**
    Successfully scraped {len(selected_names)} polling organizations.
    **Found {len(extracted_questions)} total questions** from {len(sources)} different surveys.
    Use the question selection interface to choose which questions to include in your research."""

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
            return cleaned_text[:12000]  # Limit to 8000 characters
            
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
        """Start the research design process with improved prompting"""
        self.active_sessions[session_id] = ResearchDesign(
            stage=ResearchStage.DESIGN_INPUT,
            chat_history=[]
        )
        
        # Updated initial response - removed examples
        initial_response = """
    🔬 **Research Design Workflow Started**

    Let's design your research study step by step. I'll ask you a series of questions to help create a comprehensive research design.

    **Question 1 of 4: Research Topic**
    What are you looking to find out? Please describe your research topic or area of interest.

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
        """Process research input with enhanced poll selection handling"""
        logger.info(f"Processing research input for session {session_id}: '{user_input[:50]}...'")
        
        if session_id not in self.active_sessions:
            return "Session not found. Please start a new research design session."
        
        session = self.active_sessions[session_id]
        logger.info(f"Current session stage: {session.stage}")
        
        # PRIORITY 1: Handle poll selection input FIRST
        if session.__dict__.get('awaiting_poll_selection', False):
            logger.info("Session is awaiting poll selection")
            try:
                import json
                selection_data = json.loads(user_input)
                if 'selected_polls' in selection_data:
                    logger.info(f"Processing poll selection: {selection_data['selected_polls']}")
                    return await self._handle_poll_selection(session_id, selection_data['selected_polls'])
            except:
                logger.info("Poll selection input was not JSON format")
                pass

        # Handle stage-based processing
        if session.stage == ResearchStage.DESIGN_INPUT:
            response = await self._handle_design_input(session_id, user_input)
        elif session.stage == ResearchStage.DESIGN_REVIEW:
            response = await self._handle_design_review(session_id, user_input)
        elif session.stage == ResearchStage.DECISION_POINT:
            logger.info("Processing decision point input")
            response = await self._handle_decision_point(session_id, user_input)
            logger.info(f"Decision point response: {response[:50]}...")
        elif session.stage == ResearchStage.QUESTIONNAIRE_BUILDER:
            response = await self._handle_questionnaire_builder(session_id, user_input)
        elif session.stage == ResearchStage.FINAL_OUTPUT:
            response = await self._handle_final_output(session_id, user_input)
        else:
            response = "Invalid session stage."
        
        # Check if the response indicates poll selection is needed
        if response == "POLL_SELECTION_NEEDED":
            logger.info("Research processing triggered poll selection - not logging as chat")
            return response
        
        # Log normal chat interactions
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
        elif response == 'F':
            # Fix issues based on synthetic feedback
            return await self._regenerate_questions_from_feedback(session)
        elif response == 'T':
            # Test again
            return await self._test_questions(session)
        else:
            return """
    Please respond with:
    - **Y** (Yes) - Finalize and export complete research package
    - **N** (No) - Make additional modifications  
    - **F** (Fix Issues) - Regenerate questions based on synthetic feedback
    - **T** (Test Again) - Run another round of testing
    """
    
    async def _regenerate_questions_from_feedback(self, session: ResearchDesign) -> str:
        """Regenerate questions based on synthetic feedback"""
        
        # Get the stored feedback
        synthetic_feedback = session.__dict__.get('last_synthetic_feedback', '')
        
        if not synthetic_feedback:
            return "No feedback available. Please run testing first."
        
        # Identify non-demographic questions to regenerate
        fixed_demographics = [
            "What is your age?",
            "What is your gender?", 
            "What is your highest level of education?",
            "What is your annual household income range?",
            "In which city/region do you currently live?"
        ]
        
        questions_to_regenerate = []
        demographic_questions = []
        
        for q in session.questions:
            if q in fixed_demographics:
                demographic_questions.append(q)
            else:
                questions_to_regenerate.append(q)
        
        if not questions_to_regenerate:
            return "Only demographic questions found. Demographics cannot be regenerated."
        
        # Generate improved questions based on feedback
        prompt = f"""
    Based on the synthetic respondent feedback below, regenerate improved survey questions:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}

    ORIGINAL QUESTIONS TO IMPROVE:
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(questions_to_regenerate))}

    SYNTHETIC FEEDBACK RECEIVED:
    {synthetic_feedback}

    INSTRUCTIONS:
    - Address the specific issues mentioned in the feedback
    - Improve clarity and reduce confusion
    - Fix any missing answer options
    - Simplify complex terminology
    - Keep the same number of questions ({len(questions_to_regenerate)})
    - Maintain the research objectives
    - Use professional survey language

    Generate {len(questions_to_regenerate)} improved questions:
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            # Parse improved questions
            lines = cleaned_response.split('\n')
            improved_questions = []
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 10:
                    continue
                    
                # Clean question
                clean_line = re.sub(r'^[\d\.\-\•\*\s]*', '', line).strip()
                
                if clean_line and len(clean_line) > 15:
                    if not clean_line.endswith('?') and ')' not in clean_line:
                        clean_line += '?'
                    improved_questions.append(clean_line)
            
            # Ensure we have the right number of questions
            if len(improved_questions) < len(questions_to_regenerate):
                # Fill missing questions
                for i in range(len(improved_questions), len(questions_to_regenerate)):
                    improved_questions.append(questions_to_regenerate[i])
            elif len(improved_questions) > len(questions_to_regenerate):
                improved_questions = improved_questions[:len(questions_to_regenerate)]
            
            # Combine improved questions with demographics
            session.questions = improved_questions + demographic_questions
            
            return f"""
    ✏️ **Questions Improved Based on Feedback**

    **Improved Questions ({len(improved_questions)}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(improved_questions))}

    **Fixed Demographics ({len(demographic_questions)}):**
    {chr(10).join(f"{i+len(improved_questions)+1}. {q}" for i, q in enumerate(demographic_questions))}

    **Total Questions: {len(session.questions)}**

    The questions have been improved to address the issues identified in synthetic testing.

    ---

    **Review these improved questions:**
    - **A** (Accept) - Use these questions and proceed to testing
    - **R** (Revise) - Make additional manual revisions
    - **T** (Test Now) - Test the improved questions with synthetic respondents
    - **B** (Back) - Return to questionnaire builder menu
    """
            
        except Exception as e:
            logger.error(f"Error regenerating questions from feedback: {e}")
            return "Unable to regenerate questions from feedback. Please try manual revisions or proceed with current questions."

    async def _export_complete_research_package(self, session: ResearchDesign) -> str:
        """Export complete research package with saved content and minimal LLM calls"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"complete_research_package_{timestamp}.txt"
        
        try:
            os.makedirs("research_outputs", exist_ok=True)
            
            # Use SAVED research design content (don't regenerate)
            if hasattr(session, '__dict__') and 'saved_research_design' in session.__dict__:
                research_design_content = session.__dict__['saved_research_design']
            else:
                # Fallback: create basic design from saved data without LLM
                research_design_content = f"""
    **Research Methodology:** Online survey methodology recommended for {session.target_population}
    **Key Variables:** Based on {len(session.questions or [])} questions covering the research objectives
    **Sample Size:** Recommended minimum sample size should be calculated based on target population and desired confidence level
    **Data Collection:** Online survey platform with secure data storage and privacy compliance
    """
            
            # Use APPROVED questions exactly as they are (don't regenerate)
            final_questions = session.questions or []
            
            # Remove duplicates while preserving order (but don't regenerate)
            seen = set()
            unique_final_questions = []
            for q in final_questions:
                q_lower = q.lower().strip()
                if q_lower not in seen:
                    seen.add(q_lower)
                    unique_final_questions.append(q)
            
            final_questions = unique_final_questions
            
            # Create question breakdown from saved session data (no LLM calls)
            question_source_info = self._create_saved_question_breakdown(session, final_questions)
            
            # ONLY make LLM calls for these 3 sections:
            # 1. Implementation recommendations
            implementation_content = await self._generate_implementation_recommendations(session)
            
            # 2. Ethics and considerations 
            ethics_content = await self._generate_ethics_content(session)
            
            # 3. Research checklist
            checklist_content = await self._generate_research_checklist(session)
            
            # Export chat history (no LLM call)
            chat_filepath = self._export_chat_history(session, timestamp)
            
            # Create comprehensive research package using SAVED content
            package_content = f"""COMPLETE RESEARCH DESIGN PACKAGE
    Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    ================================================================================
    RESEARCH DESIGN SUMMARY
    ================================================================================

    Research Topic: {session.research_topic}

    Research Objectives:
    {chr(10).join(f"• {obj}" for obj in (session.objectives or []))}

    Research Motivation: {session.research_motivation or 'Not specified'}

    Target Population: {session.target_population}

    Research Timeframe: {session.timeframe or 'Not specified'}

    ================================================================================
    APPROVED METHODOLOGY AND APPROACH
    ================================================================================

    {research_design_content}

    ================================================================================
    APPROVED QUESTIONNAIRE QUESTIONS
    ================================================================================

    The following questions have been designed, tested, and approved for your research:

    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(final_questions))}

    ================================================================================
    QUESTION SOURCES AND BREAKDOWN
    ================================================================================

    {question_source_info}

    ================================================================================
    EXPORTED FILES
    ================================================================================

    This research package includes the following exported files:
    - Research Package: {filename}
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
    RESEARCH VERIFICATION CHECKLIST
    ================================================================================

    {checklist_content}

    ================================================================================

    This research package is ready for implementation. All questions have been
    tested, approved, and validated. The methodology is sound and appropriate for your
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
    ✅ Approved research design and methodology (saved from session)
    ✅ {len(final_questions)} approved and tested questionnaire questions  
    ✅ LLM-generated implementation recommendations
    ✅ LLM-generated ethics and privacy considerations
    ✅ LLM-generated research verification checklist
    ✅ Complete conversation history exported

    **Your Research Summary:**
    - **Topic:** {session.research_topic}
    - **Motivation:** {session.research_motivation}
    - **Questions:** {len(final_questions)} approved questions
    - **Target:** {session.target_population}
    - **Chat interactions:** {len(session.chat_history) if session.chat_history else 0} recorded

    {self._create_saved_question_breakdown(session, final_questions)}

    Both files are ready for download from the research_outputs directory.
    Session completed successfully!
    """
            
        except Exception as e:
            logger.error(f"Error exporting research package: {str(e)}", exc_info=True)
            return f"Error creating research package: {str(e)}. Please check logs and try again."
    
    def _create_saved_question_breakdown(self, session: ResearchDesign, final_questions: List[str]) -> str:
        """SIMPLE FIX: Just use the selected questions directly - no pattern matching needed"""
        
        # Get different question types from session data
        custom_questions = session.__dict__.get('custom_questions', [])
        polling_questions = []
        generated_questions = []
        
        # Fixed demographics
        fixed_demographics = [
            "What is your age?",
            "What is your gender?",
            "What is your highest level of education?",
            "What is your annual household income range?",
            "In which city/region do you currently live?"
        ]
        
        # SIMPLE FIX: Just use user_selected_questions directly
        polling_sources = []
        
        if (hasattr(session, 'user_selected_questions') and 
            session.user_selected_questions):
            
            # Get the selected polling questions directly
            polling_questions = [q['question'] for q in session.user_selected_questions]
            
            # Get sources
            unique_sources = set()
            for q in session.user_selected_questions:
                poll_name = q.get('poll_name', '')
                source = q.get('source', '')
                
                if poll_name and poll_name != 'Unknown Poll':
                    unique_sources.add(poll_name)
                elif source and 'http' in source:
                    try:
                        from urllib.parse import urlparse
                        domain = urlparse(source).netloc
                        unique_sources.add(domain)
                    except:
                        unique_sources.add(source[:50])
                elif source:
                    unique_sources.add(source)
                else:
                    unique_sources.add("Polling Organization")
            
            polling_sources = list(unique_sources)
            logger.info(f"SIMPLE EXPORT: Using {len(polling_questions)} questions directly from user_selected_questions")
        
        # Count demographics in final_questions
        demographic_count = sum(1 for q in final_questions if q in fixed_demographics)
        
        # Identify generated questions - everything in final_questions that's NOT custom or demographic
        # (We don't need to remove polling questions from final_questions since we're showing them separately)
        for q in final_questions:
            if (q not in custom_questions and 
                q not in fixed_demographics):
                generated_questions.append(q)
        
        logger.info(f"=== SIMPLE EXPORT DEBUG ===")
        logger.info(f"Polling questions (direct): {len(polling_questions)}")
        logger.info(f"Generated questions: {len(generated_questions)}")
        logger.info(f"Custom questions: {len(custom_questions)}")
        logger.info(f"Demographics: {demographic_count}")
        
        # Build breakdown
        breakdown_lines = []
        
        # Show polling questions FIRST
        if polling_questions:
            breakdown_lines.append(f"Selected Polling Questions: {len(polling_questions)}")
            breakdown_lines.append(f"  • Questions selected from polling organizations during research")
            if polling_sources:
                breakdown_lines.append(f"  • Sources: {', '.join(polling_sources[:5])}")
            breakdown_lines.append("")
            
            breakdown_lines.append("SELECTED POLLING QUESTIONS:")
            for i, q in enumerate(polling_questions, 1):
                breakdown_lines.append(f"  {i}. {q}")
            breakdown_lines.append("")
        
        if generated_questions:
            breakdown_lines.append(f"AI Generated Questions: {len(generated_questions)}")
            breakdown_lines.append(f"  • Created based on research topic and methodology")
            breakdown_lines.append("")
            
            breakdown_lines.append("AI GENERATED QUESTIONS:")
            for i, q in enumerate(generated_questions, 1):
                breakdown_lines.append(f"  {i}. {q}")
            breakdown_lines.append("")
        
        if custom_questions:
            breakdown_lines.append(f"Custom Questions (User-Provided): {len(custom_questions)}")
            breakdown_lines.append(f"  • Questions you added during questionnaire building")
            breakdown_lines.append("")
            
            breakdown_lines.append("CUSTOM QUESTIONS:")
            for i, q in enumerate(custom_questions, 1):
                breakdown_lines.append(f"  {i}. {q}")
            breakdown_lines.append("")
        
        if demographic_count > 0:
            demographic_questions = [q for q in final_questions if q in fixed_demographics]
            breakdown_lines.append(f"Fixed Demographics: {demographic_count}")
            breakdown_lines.append(f"  • Standard demographic questions automatically included")
            breakdown_lines.append("")
            
            breakdown_lines.append("DEMOGRAPHIC QUESTIONS:")
            for i, q in enumerate(demographic_questions, 1):
                breakdown_lines.append(f"  {i}. {q}")
            breakdown_lines.append("")
        
        # Calculate total (polling + generated + custom + demographics)
        total_questions = len(polling_questions) + len(generated_questions) + len(custom_questions) + demographic_count
        breakdown_lines.append(f"Total Questions: {total_questions}")
        
        return "\n".join(breakdown_lines)

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

    async def _generate_research_checklist(self, session: ResearchDesign) -> str:
        """Generate a research verification checklist using LLM"""
        
        prompt = f"""
        Generate a comprehensive research verification checklist for this study:

        Research Topic: {session.research_topic}
        Target Population: {session.target_population}
        Questions: {len(session.questions or [])} total questions

        Create a detailed checklist of items that should be verified and completed during and after the research process. Include:
        - Pre-launch verification items
        - Data collection checkpoints  
        - Data quality verification
        - Analysis verification
        - Reporting verification
        - Ethical compliance checks

        Format as a clear checklist with checkboxes (☐) that researchers can use to ensure quality.
        Be specific and actionable for this research context.
        Respond in English only.
        """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.6)
            return remove_chinese_and_punct(str(response))
        except Exception as e:
            logger.error(f"Error generating research checklist: {e}")
            return """
    ☐ Questionnaire has been pilot tested with sample respondents
    ☐ All questions are clear and unambiguous
    ☐ Response options are comprehensive and mutually exclusive
    ☐ Target sample size has been calculated and achieved
    ☐ Data collection method ensures representative sampling
    ☐ Participant consent has been obtained where required
    ☐ Data is being collected and stored securely
    ☐ Response rate is being monitored and is acceptable
    ☐ Data quality checks are being performed regularly
    ☐ Missing data patterns have been analyzed
    ☐ Statistical analysis plan has been followed
    ☐ Results have been validated and cross-checked
    ☐ Findings are properly interpreted within study limitations
    ☐ Report includes methodology, results, and recommendations
    ☐ Ethical guidelines have been followed throughout
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
        """Handle user input during design input phase - now 4 questions with new 'why' question"""
        session = self.active_sessions[session_id]
        
        if not session.user_responses:
            session.user_responses = {}
        
        # Determine which question we're on based on existing responses
        if 'topic' not in session.user_responses:
            # This is the response to Question 1 (research topic)
            session.user_responses['topic'] = user_input.strip()
            session.research_topic = user_input.strip()
            
            logger.info(f"Session {session_id}: Saved topic - {session.research_topic}")
            
            # Updated objectives question - removed examples and changed wording
            return f"""
    **Question 2 of 4: Research Objectives**
    What specific things do you want to know about this topic?

    Please list what you want to find out (you can provide multiple objectives):
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
            
            # NEW Question 3: Why is this topic interesting?
            return f"""
    **Question 3 of 4: Research Motivation**
    Why is this topic interesting to you?

    Please describe your motivation for conducting this research:
    """
        
        elif 'motivation' not in session.user_responses:
            # This is the response to Question 3 (motivation) - NEW QUESTION
            session.user_responses['motivation'] = user_input.strip()
            session.research_motivation = user_input.strip()
            
            logger.info(f"Session {session_id}: Saved motivation - {session.research_motivation}")
            
            # Updated target population question with new examples
            return """
    **Question 4 of 4: Target Population**
    Who is your target population or study participants?

    Examples:
    - All Americans
    - Women in Urban Areas  
    - 18-29 Year Olds

    Please describe your target population:
    """
        
        elif 'target_population' not in session.user_responses:
            # This is the response to Question 4 (target population) - final question
            session.user_responses['target_population'] = user_input.strip()
            session.target_population = user_input.strip()
            
            logger.info(f"Session {session_id}: Saved target population - {session.target_population}")
            logger.info(f"Session {session_id}: All 4 questions completed, generating research design")
            
            # Generate research design summary with motivation included
            research_design = await self._generate_research_design_with_motivation(session)
            session.stage = ResearchStage.DESIGN_REVIEW
            
            return f"""
    📋 **Research Design Summary**

    **Topic:** {session.research_topic}

    **Objectives:**
    {chr(10).join(f"• {obj}" for obj in session.objectives)}

    **Motivation:** {session.research_motivation}

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
    
    async def _generate_research_design_with_motivation(self, session: ResearchDesign) -> str:
        """Generate comprehensive research design with enhanced research integration"""
        
        # Store current session for research URL processing
        self._current_session = session
        
        # Enhanced research search with screenshots - FIXED: Store results for UI access
        related_research = await self._search_related_research(session.research_topic)
        
        # IMPORTANT: After research search, check if screenshots were captured and flag for UI
        if (hasattr(session, 'research_screenshots') and 
            session.research_screenshots and 
            len(session.research_screenshots) > 0):
            
            # Set a flag to indicate research screenshots are ready for UI
            session.__dict__['has_research_screenshots'] = True
            session.__dict__['research_screenshots_count'] = len(session.research_screenshots)
            logger.info(f"Research design generated with {len(session.research_screenshots)} screenshots ready for UI")
        
        prompt = f"""
        Generate a comprehensive research design based on the following information:

        Topic: {session.research_topic}
        Objectives: {', '.join(session.objectives)}
        Motivation: {session.research_motivation}
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
            
            # Append related research if found
            if related_research:
                cleaned_response += f"\n\n**Related Research Studies:**\n{related_research}"
            
            return cleaned_response
        except Exception as e:
            logger.error(f"Error generating research design: {e}")
            return "Unable to generate research design automatically. Please review your inputs manually."

    async def _summarize_research_content(self, content: str, title: str) -> str:
        """Summarize research content to extract key findings in one line only"""
        
        # Limit content length for processing
        content_sample = content[:4000]
        
        prompt = f"""
        Summarize this research study in EXACTLY ONE sentence (maximum 15 words):

        Study Title: {title}
        Content: {content_sample}

        Focus ONLY on the main finding or conclusion. Do NOT mention sample size, methodology, or participants.
        
        EXAMPLES:
        - "Shows 73% of parents consider school safety their top concern"
        - "Finds strong public support for background checks on gun purchases"
        - "Reports declining confidence in school security measures"

        Provide EXACTLY ONE sentence under 15 words about the main finding:
        """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.3)  # Lower temperature for consistency
            summary = remove_chinese_and_punct(str(response)).strip()
            
            # Clean up and ensure it's a single sentence
            summary = summary.split('.')[0]  # Take only first sentence
            if summary:
                summary = summary.strip()
                if not summary.endswith('.'):
                    summary += '.'
            
            # Limit to 15 words maximum
            words = summary.split()
            if len(words) > 15:
                summary = ' '.join(words[:15]) + '.'
                
            return summary if summary else "Research study with relevant findings for your topic."
        except Exception as e:
            logger.error(f"Error summarizing research content: {e}")
            return "Research study with relevant findings for your topic."

    async def _collect_research_urls(self, research_topic: str, target_count: int = 10) -> List[str]:
        """Collect research URLs using RESEARCH-SPECIFIC search terms (different from internet search)"""
        try:
            # RESEARCH-SPECIFIC search variations (different from internet search)
            search_variations = [
                f"{research_topic} academic research study",
                f"{research_topic} peer reviewed research",
                f"{research_topic} research findings analysis", 
                f"{research_topic} university research study"
            ]
            
            all_unique_urls = []
            seen_urls = set()
            
            for search_term in search_variations:
                if len(all_unique_urls) >= target_count:
                    break
                    
                try:
                    search_result = self.search_service.cse().list(
                        q=search_term,
                        cx=self.google_cse_id,
                        num=10,
                        safe='active',
                        fields='items(title,link,snippet)'
                    ).execute()
                    
                    if 'items' in search_result:
                        for item in search_result['items']:
                            link = item.get('link', '')
                            
                            if link and link not in seen_urls:
                                if self._is_valid_url(link):
                                    all_unique_urls.append(link)
                                    seen_urls.add(link)
                                    logger.info(f"✅ Collected research URL #{len(all_unique_urls)}: {link}")
                                    
                                    if len(all_unique_urls) >= target_count:
                                        break
                    
                    await asyncio.sleep(1)
                    
                except Exception as api_error:
                    logger.error(f"Research search API error for '{search_term}': {api_error}")
                    continue
            
            logger.info(f"Research URL collection: {len(all_unique_urls)} URLs collected (will only mark successful ones)")
            return all_unique_urls[:target_count]
            
        except Exception as e:
            logger.error(f"Error collecting research URLs: {e}")
            return []

    def _is_topic_related_url(self, url: str, research_topic: str) -> bool:
        """Check if URL path contains keywords related to research topic"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url.lower())
            url_path = parsed.path.lower()
            
            # Extract keywords from research topic
            topic_keywords = [word.lower() for word in research_topic.split() if len(word) > 3]
            
            # Check if any topic keyword appears in URL path
            for keyword in topic_keywords:
                if keyword in url_path:
                    return True
            
            # Also check for research-related terms in URL
            research_indicators = ['research', 'study', 'survey', 'analysis', 'report']
            for indicator in research_indicators:
                if indicator in url_path:
                    return True
            
            return False
            
        except Exception:
            return False

    async def _is_content_topic_related(self, content: str, research_topic: str, url: str) -> bool:
        """Use LLM to determine if content is related to research topic"""
        
        # Limit content for processing
        content_sample = content[:2000]
        
        prompt = f"""
        Determine if this webpage content is related to the research topic "{research_topic}".
        
        Content sample from {url}:
        {content_sample}
        
        Respond with ONLY "YES" if the content is clearly related to "{research_topic}" research, studies, or surveys.
        Respond with ONLY "NO" if the content is not related.
        
        Response:
        """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.1)
            cleaned_response = remove_chinese_and_punct(str(response)).strip().upper()
            
            return "YES" in cleaned_response
            
        except Exception as e:
            logger.error(f"Error checking content relevance for {url}: {e}")
            return False

    async def _validate_and_select_research_urls(self, urls: List[str], research_topic: str, target_count: int = 3) -> List[str]:
        """Validate URLs and select those related to research topic"""
        legitimate_urls = []
        
        for url in urls:
            if len(legitimate_urls) >= target_count:
                break
                
            try:
                # Check if URL is topic-related by examining the URL path
                if self._is_topic_related_url(url, research_topic):
                    logger.info(f"✅ URL path matches topic: {url}")
                    legitimate_urls.append(url)
                    continue
                
                # If URL path doesn't match, check content relevance
                content = await self._scrape_page_content(url)
                if content and len(content) > 300:
                    is_relevant = await self._is_content_topic_related(content, research_topic, url)
                    if is_relevant:
                        logger.info(f"✅ Content matches topic: {url}")
                        legitimate_urls.append(url)
                    else:
                        logger.info(f"❌ Content not relevant: {url}")
                else:
                    logger.info(f"❌ Insufficient content: {url}")
                    
            except Exception as e:
                logger.warning(f"Error validating research URL {url}: {e}")
                continue
        
        logger.info(f"Selected {len(legitimate_urls)} legitimate research URLs")
        return legitimate_urls
        
    async def _create_individual_research_summary(self, content: str, url: str, research_topic: str) -> str:
        """Create individual LLM summary for each research URL"""
        
        content_sample = content[:4000]
        
        prompt = f"""
        Create a concise one-sentence summary of this research study related to "{research_topic}".
        
        Research URL: {url}
        Content: {content_sample}
        
        Requirements:
        - EXACTLY one sentence (maximum 20 words)
        - Focus ONLY on the main finding or conclusion
        - Do NOT mention methodology, sample size, or participants
        - Be specific about what was discovered or concluded
        
        Examples:
        - "Shows 73% of parents consider school safety their top concern"
        - "Finds strong public support for background checks on gun purchases"
        - "Reports declining confidence in school security measures"
        
        Summary:
        """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.3)
            summary = remove_chinese_and_punct(str(response)).strip()
            
            # Clean up and ensure it's a single sentence
            summary = summary.split('.')[0]
            if summary:
                summary = summary.strip()
                if not summary.endswith('.'):
                    summary += '.'
            
            # Limit to 20 words maximum
            words = summary.split()
            if len(words) > 20:
                summary = ' '.join(words[:20]) + '.'
                
            return summary if summary else "Research study with relevant findings."
            
        except Exception as e:
            logger.error(f"Error creating research summary for {url}: {e}")
            return "Research study with relevant findings."
            
    async def _capture_research_screenshots(self, urls: List[str]) -> List[Dict]:
        """Capture screenshots for research URLs"""
        screenshots = []
        
        for url in urls:
            try:
                if self.browser_tool:
                    screenshot = await capture_url_screenshot(url, self.browser_tool)
                    
                    if screenshot:
                        is_valid = await self.validate_screenshot(screenshot, url)
                        if is_valid:
                            domain = self._extract_domain(url)
                            screenshots.append({
                                'url': url,
                                'screenshot': screenshot,
                                'title': f"Research Study - {domain}"
                            })
                            logger.info(f"✅ Research screenshot captured: {domain}")
                        else:
                            logger.warning(f"⚠️ Invalid research screenshot: {url}")
                    else:
                        logger.warning(f"⚠️ No research screenshot captured: {url}")
                        
            except Exception as e:
                logger.warning(f"Error capturing research screenshot for {url}: {e}")
                continue
        
        logger.info(f"Captured {len(screenshots)} research screenshots")
        return screenshots

    async def _search_related_research(self, research_topic: str) -> str:
        """FIXED: Research search that only marks the final 3 successful URLs"""
        
        if not self.search_service:
            return ""
        
        try:
            # Get URL processor
            url_processor = self._get_url_processor()
            
            # Collect URLs for RESEARCH (different search terms than internet search)
            collected_urls = await self._collect_research_urls(research_topic, target_count=10)
            if not collected_urls:
                return ""
            
            # Process URLs with unified approach - scrape once, validate once, screenshot once
            # Do NOT mark URLs yet - only mark the ones that actually succeed
            result = await url_processor.process_urls_for_research(
                collected_urls, research_topic, target_count=1
            )
            
            # CRITICAL: Only mark the URLs that actually made it to the final research design
            if result['processed_urls']:
                for successful_url in result['processed_urls']:
                    url_processor.mark_research_url_processed(successful_url)
                    logger.info(f"🔬 Marked successful research URL: {successful_url}")
            
            # Store results in session
            if hasattr(self, '_current_session') and self._current_session:
                session = self._current_session
                if session.research_screenshots is None:
                    session.research_screenshots = []
                
                if result['screenshots']:
                    session.research_screenshots.extend(result['screenshots'])
                    logger.info(f"Stored {len(result['screenshots'])} research screenshots")
            
            # Format output
            if result['research_summaries']:
                formatted_research = []
                for i, research in enumerate(result['research_summaries'], 1):
                    formatted_research.append(
                        f"{i}. **[{research['domain']}]({research['url']})** - {research['summary']}"
                    )
                return "\n".join(formatted_research)
            
            return ""
            
        except Exception as e:
            logger.error(f"Error in research search: {e}")
            return ""

    def _is_legitimate_research_source(self, url: str, title: str, snippet: str) -> bool:
        """Check if a source appears to be legitimate research"""
        
        # Academic and research domains
        trusted_domains = [
            'edu', 'org', 'gov', 'researchgate.net', 'scholar.google.com',
            'pubmed.ncbi.nlm.nih.gov', 'jstor.org', 'springer.com',
            'tandfonline.com', 'sage', 'wiley.com', 'plos.org', 'com'
        ]
        
        # Research indicators in title/snippet
        research_indicators = [
            'study', 'research', 'survey', 'analysis', 'findings',
            'results', 'data', 'methodology', 'sample', 'participants',
            'questionnaire', 'statistical', 'empirical'
        ]
        
        # Check domain
        url_lower = url.lower()
        domain_match = any(domain in url_lower for domain in trusted_domains)
        
        # Check content indicators
        text_lower = (title + ' ' + snippet).lower()
        content_match = sum(1 for indicator in research_indicators if indicator in text_lower) >= 2
        
        return domain_match or content_match

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
        session = self.active_sessions[session_id]
        response = user_input.upper().strip()
        logger.info(f"🔍 DEBUG: _handle_design_review called with response: '{response}'")
        
        if response == 'Y':
            logger.info("🔍 DEBUG: User approved design, setting up poll selection")
            session.stage = ResearchStage.DATABASE_SEARCH
            # Set poll selection flags BEFORE returning
            active_polls = PollingSiteConfig.get_active_polls(session.research_topic)
            session.__dict__['available_polls'] = active_polls
            session.__dict__['show_poll_selection'] = True
            session.__dict__['awaiting_poll_selection'] = True
            logger.info(f"🔍 DEBUG: Set poll flags - available_polls: {len(active_polls)}, show_poll_selection: {session.__dict__.get('show_poll_selection')}")
            logger.info("🔍 DEBUG: Returning POLL_SELECTION_NEEDED to trigger UI")
            return "POLL_SELECTION_NEEDED"
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
    - **Y** (Yes) - Proceed to select polling sources
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
        """Search internet and present questions for selection with UI data - FIXED to exclude research URLs"""
        try:
            # IMPORTANT: Get URL processor and ensure research URLs are properly tracked
            url_processor = self._get_url_processor()
            
            # CRITICAL FIX: If we have research screenshots, mark those URLs as processed for research
            if hasattr(session, 'research_screenshots') and session.research_screenshots:
                for screenshot in session.research_screenshots:
                    research_url = screenshot.get('url')
                    if research_url:
                        url_processor.mark_research_url_processed(research_url)
                        logger.info(f"🔒 Marked research URL as processed: {research_url}")
            
            # Additional safety: Check for any cached research content and mark those URLs too
            if hasattr(url_processor, 'content_cache'):
                for cached_url in list(url_processor.content_cache.keys()):
                    if url_processor.is_url_already_processed_for_research(cached_url):
                        logger.info(f"🔒 Research URL already in cache: {cached_url}")
                        continue
            
            # Now start fresh internet search with completely different URLs
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
            
            # Handle screenshots properly - DON'T mix with research screenshots - FIXED NULL CHECKS
            if screenshots:
                # Initialize internet-only screenshots list if None
                if session.screenshots is None:
                    session.screenshots = []
                
                # IMPORTANT: Only add NEW internet search screenshots (not research screenshots)
                # Research screenshots are already stored separately in session.research_screenshots
                session.screenshots.extend(screenshots)
                logger.info(f"Added {len(screenshots)} INTERNET SEARCH screenshots. Total: {len(session.screenshots)}")
            
            session.extracted_questions_with_sources = session.selected_questions_pool
            
            # Move to selection stage
            session.stage = ResearchStage.DECISION_POINT
            session.awaiting_selection = True
            
            # Format questions for UI selection
            ui_selection_data = self._format_questions_for_ui_selection(session.selected_questions_pool)
            
            # Store UI data in session for frontend access
            session.__dict__['ui_selection_data'] = ui_selection_data
            
            # IMPORTANT: Set a flag to trigger UI
            session.__dict__['trigger_question_selection_ui'] = True
            
            total_collected = len(session.all_collected_urls) if session.all_collected_urls else 0
            current_batch = session.current_batch_index
            processed_count = len(session.browsed_urls) if session.browsed_urls else 0
            
            currently_selected_count = len(session.user_selected_questions)
            remaining_selections = session.max_selectable_questions - currently_selected_count
            
            # Log URL separation for debugging
            research_urls = url_processor.processed_research_urls
            internet_urls = url_processor.processed_internet_urls
            logger.info(f"📊 URL Tracking Status:")
            logger.info(f"  - Research URLs tracked: {len(research_urls)}")
            logger.info(f"  - Internet URLs tracked: {len(internet_urls)}")
            logger.info(f"  - No overlap should exist between these sets")
            
            # Add a special marker for the frontend to detect
            response_text = f"""🔍 **Questions Found - Please Select (Batch {current_batch}/{(total_collected + 5) // 6})**

    Found {len(new_unique_questions)} new questions from this batch.
    **Total pool now: {len(session.selected_questions_pool)} questions**

    **📊 Selection Status:**
    - **Currently selected:** {currently_selected_count}/{session.max_selectable_questions}
    - **Remaining selections:** {remaining_selections}
    - **URLs processed:** {processed_count} of {total_collected} collected

    Use the checkboxes in the interface to select up to {remaining_selections} more questions.

    **Options after selection:**
    - **Continue** - Proceed with selected questions
    - **Rebrowse** - Search more URLs after selection
    - **Exit** - Exit workflow

    [UI_SELECTION_TRIGGER]"""  # Special marker for frontend
            
            return response_text
            
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

    def _format_questions_for_ui_selection(self, questions_pool: List[Dict]) -> Dict:
        """FIXED: Format questions for UI selection with FULL deep URLs displayed correctly"""
        if not questions_pool:
            return {"questions": [], "sources": []}
        
        # Group by actual source URL for better organization
        source_groups = {}
        formatted_questions = []
        
        for i, q_dict in enumerate(questions_pool):
            # CRITICAL FIX: Use the actual FULL source URL from the question data
            source_url = q_dict.get('source', '')
            poll_name = q_dict.get('poll_name', 'Unknown Poll')
            survey_name = q_dict.get('survey_name', 'Unknown Survey')
            
            # Debug logging for source URL extraction
            logger.debug(f"Processing question {i+1}: source_url='{source_url}', poll_name='{poll_name}'")
            
            # Validate that we have a proper URL
            if not source_url or not source_url.startswith(('http://', 'https://')):
                # Fallback: construct URL if missing
                if poll_name and poll_name != 'Unknown Poll':
                    source_url = f"https://{poll_name.lower().replace(' ', '').replace('university', '').replace('college', '').replace('school', '')}.edu"
                else:
                    source_url = "https://unknown-source.com"
            
            question_id = f"q_{i+1}"
            
            # Use the FULL URL as the grouping key
            if source_url not in source_groups:
                source_groups[source_url] = []
            
            question_data = {
                "id": question_id,
                "index": i,
                "question": q_dict['question'],
                "source": source_url,  # KEEP FULL DEEP URL
                "display_source": source_url,  # ALSO use full URL for display
                "poll_name": poll_name,
                "survey_name": survey_name,
                "extraction_method": q_dict.get('extraction_method', 'unknown')
            }
            
            source_groups[source_url].append(question_data)
            formatted_questions.append(question_data)
        
        # Format sources for display with FULL URLs
        formatted_sources = []
        for source_num, (source_url, questions) in enumerate(source_groups.items(), 1):
            first_question = questions[0]
            poll_name = first_question.get('poll_name', 'Unknown Poll')
            
            # Extract domain for display purposes but show FULL URL as primary
            try:
                from urllib.parse import urlparse
                parsed = urlparse(source_url)
                domain = parsed.netloc if source_url else 'Unknown'
            except:
                domain = 'Unknown'
            
            # CRITICAL FIX: Make sure the full_url field contains the complete deep URL
            formatted_sources.append({
                "id": f"source_{source_num}",
                "domain": domain,  # Domain for backwards compatibility
                "full_url": source_url,  # CRITICAL: This must be the FULL deep URL
                "display_url": source_url,  # ADDED: Also ensure display URL is full
                "poll_name": poll_name,
                "display_name": poll_name,  # Clean poll name only
                "question_count": len(questions),
                "questions": questions
            })
        
        return {
            "questions": formatted_questions,
            "sources": formatted_sources,
            "total_count": len(formatted_questions)
        }

    async def _handle_decision_point(self, session_id: str, user_input: str) -> str:
        """Handle decision point with question selection logic - FIXED rebrowse poll selection"""
        session = self.active_sessions[session_id]
        response = user_input.strip()
        
        logger.info(f"Decision point handling: '{response}' for session {session_id}")
        
        # Handle "C" or "Continue" command - go to questionnaire builder
        if response.upper() in ['C', 'CONTINUE']:
            logger.info("User chose to continue to questionnaire builder")
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
            logger.info("Processing question selection input")
            return await self._handle_question_selection(session_id, response)
        
        # Handle rebrowse command
        if response.upper() in ['R', 'REBROWSE']:
            logger.info(f"User requested rebrowse (current count: {session.rebrowse_count})")
            
            # Check if rebrowse is still allowed
            if session.rebrowse_count >= 4:
                logger.info("Maximum rebrowse attempts reached")
                return await self._show_final_selection_summary(session)
            
            # Call rebrowse which will return POLL_SELECTION_NEEDED
            rebrowse_result = await self._rebrowse_internet(session)
            
            logger.info(f"Rebrowse result: {rebrowse_result}")
            
            # If rebrowse requests poll selection, return the special code
            if rebrowse_result == "POLL_SELECTION_NEEDED":
                logger.info("Rebrowse triggered poll selection - returning special code")
                return "POLL_SELECTION_NEEDED"
            else:
                return rebrowse_result
                
        elif response.upper() in ['E', 'EXIT']:
            logger.info("User chose to exit workflow")
            del self.active_sessions[session_id]
            return "Research design workflow ended. Thank you!"
        else:
            return """
    Please respond with:
    - **Continue** - Proceed to questionnaire builder with selected questions
    - **Rebrowse** - Search more URLs for additional questions
    - **Exit** - Exit workflow

    Or use the question selection interface to choose specific questions.
    """

    async def _handle_question_selection(self, session_id: str, user_input: str) -> str:
        """Handle user's question selection input from UI or text"""
        session = self.active_sessions[session_id]
        # Check if input is from UI (JSON format with selected question IDs)
        if user_input.strip().startswith('{') and 'selected_questions' in user_input:
            try:
                import json
                selection_data = json.loads(user_input)
                selected_question_ids = selection_data.get('selected_questions', [])
                # Convert question IDs to question dictionaries
                newly_selected = []
                for question_id in selected_question_ids:
                    # Extract index from question ID (e.g., "q_5" -> index 4)
                    try:
                        index = int(question_id.split('_')[1]) - 1


                        if 0 <= index < len(session.selected_questions_pool):

                            question_dict = session.selected_questions_pool[index]

                            # Check if already selected
                            already_selected = any(
                                q['question'].lower().strip() == question_dict['question'].lower().strip() 
                                for q in session.user_selected_questions
                            )

                            if not already_selected:
                                newly_selected.append(question_dict)
                    except (ValueError, IndexError):
                        continue
                
                # Check selection limits
                currently_selected_count = len(session.user_selected_questions)
                remaining_selections = session.max_selectable_questions - currently_selected_count

                if len(newly_selected) > remaining_selections:
                    # Don't change awaiting_selection state, stay in selection mode
                    return f"""
    ❌ **Too Many Selections**

    You can only select {remaining_selections} more questions.
    You selected {len(newly_selected)} questions.

    Please select {remaining_selections} or fewer questions using the interface.
    """

                # Add selected questions to user's selection
                session.user_selected_questions.extend(newly_selected)
                session.awaiting_selection = False  # Selection complete

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
    - **Continue** - Proceed to questionnaire builder with these questions
    - **Exit** - Exit workflow
    """
                
                return f"""
    ✅ **Questions Added to Selection**

    Added {len(newly_selected)} questions to your selection.

    **Your Selected Questions ({total_selected}/{session.max_selectable_questions}):**
    {selected_questions_text}

    **Remaining selections:** {remaining_selections}

    **What would you like to do?**
    - **Continue** - Proceed to questionnaire builder with selected questions
    - **Rebrowse** - Search more URLs for additional questions  
    - **Exit** - Exit workflow
    """
                
            except json.JSONDecodeError:
                pass  # Fall through to text-based processing
        
        # Handle text commands
        if user_input.upper().strip() in ['C', 'CONTINUE']:
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
        
        elif user_input.upper().strip() in ['R', 'REBROWSE']:
            # Trigger rebrowse while maintaining selection state
            session.awaiting_selection = False  # Temporarily clear for rebrowse
            return await self._rebrowse_internet(session)
        
        elif user_input.upper().strip() in ['E', 'EXIT']:
            del self.active_sessions[session_id]
            return "Research design workflow ended. Thank you!"
        
        # Handle text-based selection (fallback for backward compatibility)
        try:
            if user_input.strip() == "0":
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

    Please select {remaining_selections} or fewer questions.
    """
            
            # Add selected questions to user's selection
            newly_selected = []
            for num in selected_numbers:
                question_dict = session.selected_questions_pool[num - 1]
                
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
            
            return f"""
    ✅ **Questions Added to Selection**

    Added {len(newly_selected)} questions to your selection.

    **Your Selected Questions ({total_selected}/{session.max_selectable_questions}):**
    {selected_questions_text}

    **Remaining selections:** {remaining_selections}

    **What would you like to do?**
    - **Continue** - Proceed to questionnaire builder with selected questions
    - **Rebrowse** - Search more URLs for additional questions  
    - **Exit** - Exit workflow
    """
            
        except Exception as e:
            logger.error(f"Error handling question selection: {e}")
            return f"""
    ❌ **Selection Error**

    Please use the checkboxes in the interface to select questions, or enter one of these commands:
    - **Continue** - Proceed with current selection
    - **Rebrowse** - Find more questions
    - **Exit** - Exit workflow

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
        """FIXED: Show current questions with proper categorization including polling questions"""
        if not session.questions:
            return "No questions generated yet."
        
        fixed_demographics = [
            "What is your age?",
            "What is your gender?",
            "What is your highest level of education?",
            "What is your annual household income range?",
            "In which city/region do you currently live?"
        ]
        
        # Categorize questions properly
        custom_questions = session.__dict__.get('custom_questions', [])
        polling_questions = []
        generated_questions = []
        demographic_questions = []
        
        # Get polling questions from user selection
        if (hasattr(session, 'user_selected_questions') and 
            session.user_selected_questions):
            polling_questions = [q['question'] for q in session.user_selected_questions]
        
        # Categorize all questions
        for q in session.questions:
            if q in fixed_demographics:
                demographic_questions.append(q)
            elif q in custom_questions:
                continue  # Custom questions will be shown separately
            elif q in polling_questions:
                continue  # Polling questions will be shown separately  
            else:
                generated_questions.append(q)
        
        # Build display
        sections = []
        question_counter = 1
        
        if generated_questions:
            sections.append(f"**AI Generated Questions ({len(generated_questions)}):**")
            for q in generated_questions:
                sections.append(f"{question_counter}. {q}")
                question_counter += 1
            sections.append("")
        
        if polling_questions:
            sections.append(f"**Selected Polling Questions ({len(polling_questions)}):**")
            for q in polling_questions:
                sections.append(f"{question_counter}. {q}")
                question_counter += 1
            sections.append("")
        
        if custom_questions:
            sections.append(f"**Your Custom Questions ({len(custom_questions)}):**")
            for q in custom_questions:
                sections.append(f"{question_counter}. {q}")
                question_counter += 1
            sections.append("")
        
        if demographic_questions:
            sections.append(f"**Demographics ({len(demographic_questions)}):**")
            for q in demographic_questions:
                sections.append(f"{question_counter}. {q}")
                question_counter += 1
        
        display_content = "\n".join(sections)
        
        return f"""📋 **Current Questionnaire ({len(session.questions)} questions)**

{display_content}

---

**Review these questions:**
- **A** (Accept) - Use these questions and proceed to testing
- **R** (Revise) - Rephrase questions in different words
- **M** (More) - Generate additional questions
- **B** (Back) - Return to questionnaire builder menu"""

    async def _rebrowse_internet(self, session: ResearchDesign) -> str:
        """Rebrowse shows poll selection UI instead of using previous polls - FIXED"""
        try:
            # Check rebrowse limit
            if session.rebrowse_count >= 4:
                return await self._show_final_selection_summary(session)
            
            # Increment rebrowse count
            session.rebrowse_count += 1
            
            logger.info(f"Starting rebrowse attempt {session.rebrowse_count}/4")
            
            # CRITICAL: Clear previous poll selection and reset flags
            session.__dict__['selected_polls'] = []  # Clear previous selection
            session.__dict__['poll_selection_completed'] = False  # Reset completion flag
            session.__dict__['awaiting_poll_selection'] = True
            session.__dict__['show_poll_selection'] = True
            
            # Get available polls for selection
            active_polls = PollingSiteConfig.get_active_polls(session.research_topic)
            session.__dict__['available_polls'] = active_polls
            
            if not active_polls:
                return """❌ **No Polling Sites Available**
    No polling site scrapers are currently implemented. Please check back later."""
            
            logger.info(f"Rebrowse: Set poll selection flags for {len(active_polls)} available polls")
            
            # CRITICAL: Return special code that triggers poll selection UI
            return "POLL_SELECTION_NEEDED"
            
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
    - "5 general, 0 open-ended" (for 5 additional)
    - "8 general, 2 open-ended" (for 10 additional) 
    - "all general questions" (for any additional count)

    **Question Types:**
    - **General**: Satisfaction, rating, frequency, importance (Likert scales)
    - **Open-ended**: What, why, suggestions, feelings
    - **Close-ended**: Yes/No, multiple choice with options

    **Note:** 5 demographic questions (age, gender, education, income, location) will be automatically added at the end.

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
    async def _generate_specific_question_type(self, session: ResearchDesign, question_type: str, count: int, audience_style: str, avoid_duplicates: list = None) -> list:
        """Generate specific type of questions with choices for close-ended on same line"""
        
        avoid_list = ""
        if avoid_duplicates:
            avoid_list = f"\nAVOID creating questions similar to these existing ones:\n{chr(10).join(f'- {q}' for q in avoid_duplicates[-10:])}"
        
        if question_type == "general":
            prompt = f"""
    Generate EXACTLY {count} general survey questions (satisfaction, frequency, rating, importance - Likert scales) for this research:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}
    Questioning style: {audience_style}

    REQUIREMENTS:
    - EXACTLY {count} questions
    - All questions should use Likert scales (1-5 or 1-7 rating scales)
    - Include satisfaction, frequency, importance, and rating questions
    - Each question should be unique and distinct
    - NO demographic questions
    - Return ONLY the questions, numbered 1-{count}{avoid_list}

    Generate exactly {count} general survey questions:
    """
        
        elif question_type == "open_ended":
            prompt = f"""
    Generate EXACTLY {count} open-ended survey questions for this research:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}
    Questioning style: {audience_style}

    REQUIREMENTS:
    - EXACTLY {count} questions
    - All questions should be open-ended (What, Why, How, Describe, Explain)
    - Each question should encourage detailed responses
    - Each question should be unique and distinct
    - NO demographic questions
    - Return ONLY the questions, numbered 1-{count}{avoid_list}

    Generate exactly {count} open-ended questions:
    """
        
        elif question_type == "close_ended":
            prompt = f"""
    Generate EXACTLY {count} close-ended survey questions with multiple choice options for this research:

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}
    Questioning style: {audience_style}

    REQUIREMENTS:
    - EXACTLY {count} questions
    - All questions should be close-ended with 3-5 multiple choice options
    - Include Yes/No questions and multiple choice questions
    - Each question should be unique and distinct
    - NO demographic questions
    - CRITICAL: Put all options on the SAME LINE as the question
    - Format: "Question text? A) Option 1 B) Option 2 C) Option 3 D) Option 4"
    - Do NOT put options on separate lines
    - Return ONLY the questions with choices, numbered 1-{count}{avoid_list}

    EXAMPLE FORMAT:
    1. Do you support gun control measures? A) Yes B) No C) Somewhat D) Not sure
    2. How often do you feel safe at school? A) Always B) Usually C) Sometimes D) Rarely E) Never

    Generate exactly {count} close-ended questions with choices ON THE SAME LINE:
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            cleaned_response = remove_chinese_and_punct(str(response))
            
            # Parse questions
            lines = cleaned_response.split('\n')
            questions = []
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 10:
                    continue
                    
                # Skip instructional text
                if any(skip in line.lower() for skip in ['note:', 'requirements:', 'instructions:', 'generate', 'example']):
                    continue
                
                # Clean question
                clean_line = re.sub(r'^[\d\.\-\•\*\s]*', '', line).strip()
                
                if clean_line and len(clean_line) > 15:
                    # For close-ended questions, don't add ? if it already has options
                    if question_type == "close_ended":
                        # Check if it already has options (contains A) or B) etc.)
                        if not re.search(r'[A-E]\)', clean_line):
                            if not clean_line.endswith('?'):
                                clean_line += '?'
                    else:
                        # For other types, add ? if missing
                        if not clean_line.endswith('?'):
                            clean_line += '?'
                    
                    questions.append(clean_line)
                    
                    if len(questions) >= count:
                        break
            
            # Fill with fallback if needed
            while len(questions) < count:
                if question_type == "general":
                    questions.append(f"How satisfied are you with {session.research_topic}?")
                elif question_type == "open_ended":
                    questions.append(f"What improvements would you suggest for {session.research_topic}?")
                elif question_type == "close_ended":
                    questions.append(f"Do you support {session.research_topic} policies? A) Yes B) No C) Not sure")
            
            return questions[:count]
            
        except Exception as e:
            logger.error(f"Error generating {question_type} questions: {e}")
            # Return fallback questions
            fallback_questions = []
            for i in range(count):
                if question_type == "general":
                    fallback_questions.append(f"How satisfied are you with {session.research_topic}?")
                elif question_type == "open_ended":
                    fallback_questions.append(f"What improvements would you suggest for {session.research_topic}?")
                elif question_type == "close_ended":
                    fallback_questions.append(f"Do you support {session.research_topic} policies? A) Yes B) No C) Not sure")
            return fallback_questions

    async def _generate_ai_questions(self, session: ResearchDesign, count: int, breakdown: str, audience_style: str) -> list:
        """Generate AI questions with specified count and breakdown - NO demographics, strict type adherence"""
        import re
        if count <= 0:
            return []
        
        # Parse breakdown more strictly - only handle general, open-ended, and close-ended
        general_count = 0
        open_ended_count = 0
        close_ended_count = 0
        
        if "all general" in breakdown.lower():
            general_count = count
            open_ended_count = 0
            close_ended_count = 0
        else:
            # Extract counts for each type
            general_match = re.search(r'(\d+)\s+general', breakdown.lower())
            if general_match:
                general_count = int(general_match.group(1))
            
            open_match = re.search(r'(\d+)\s+open[- ]?ended?', breakdown.lower())
            if open_match:
                open_ended_count = int(open_match.group(1))
                
            close_match = re.search(r'(\d+)\s+close[- ]?ended?', breakdown.lower())
            if close_match:
                close_ended_count = int(close_match.group(1))
        
        # Adjust if breakdown doesn't add up
        current_total = general_count + open_ended_count + close_ended_count
        if current_total != count:
            remaining = count - open_ended_count - close_ended_count
            general_count = max(0, remaining)
        
        all_questions = []
        
        # Generate each type separately to avoid duplicates
        if general_count > 0:
            general_questions = await self._generate_specific_question_type(
                session, "general", general_count, audience_style
            )
            all_questions.extend(general_questions)
        
        if open_ended_count > 0:
            open_ended_questions = await self._generate_specific_question_type(
                session, "open_ended", open_ended_count, audience_style
            )
            all_questions.extend(open_ended_questions)
            
        if close_ended_count > 0:
            close_ended_questions = await self._generate_specific_question_type(
                session, "close_ended", close_ended_count, audience_style
            )
            all_questions.extend(close_ended_questions)
        
        # Ensure no duplicates using set-based deduplication
        seen_questions = set()
        unique_questions = []
        
        for question in all_questions:
            question_lower = question.lower().strip()
            # Create a normalized version for comparison
            normalized = re.sub(r'[^\w\s]', '', question_lower)
            if normalized not in seen_questions:
                seen_questions.add(normalized)
                unique_questions.append(question)
        
        # If we lost questions due to deduplication, generate more
        while len(unique_questions) < count:
            additional_needed = count - len(unique_questions)
            additional_questions = await self._generate_specific_question_type(
                session, "general", additional_needed, audience_style, avoid_duplicates=unique_questions
            )
            
            for question in additional_questions:
                question_lower = question.lower().strip()
                normalized = re.sub(r'[^\w\s]', '', question_lower)
                if normalized not in seen_questions:
                    seen_questions.add(normalized)
                    unique_questions.append(question)
                    if len(unique_questions) >= count:
                        break
            
            # Prevent infinite loop
            if len(additional_questions) == 0:
                break
        
        return unique_questions[:count]

    async def _generate_questions_from_specifications(self, session: ResearchDesign) -> str:
        """Generate questions based on specifications - handling all decision modes with fixed demographics automatically added"""
        
        # Determine which mode we're in
        is_selection_mode = hasattr(session, 'selected_internet_questions') and session.selected_internet_questions
        is_include_all_mode = hasattr(session, 'include_all_internet_questions') and session.include_all_internet_questions
        
        # Get basic specifications
        breakdown = session.questionnaire_responses['question_breakdown'].lower()
        audience_style = session.questionnaire_responses['audience_style']
        
        # Fixed demographic questions - these will ALWAYS be added at the end
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
        
        # Generate the required questions (NO demographics in AI generation - they're added automatically)
        if questions_to_generate > 0:
            generated_questions = await self._generate_ai_questions(
                session, questions_to_generate, breakdown, audience_style
            )
        else:
            generated_questions = []
        
        # Combine questions based on mode + AUTOMATICALLY ADD FIXED DEMOGRAPHICS AT THE END
        if is_include_all_mode:
            # Y option: Internet questions + generated questions + demographics (auto-added)
            final_questions = (session.internet_questions or []) + generated_questions + fixed_demographics
            
            display_info = f"""**All Internet Questions ({len(session.internet_questions or [])}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(session.internet_questions or []))}

    {"**Additional Generated Questions (" + str(len(generated_questions)) + "):**" if generated_questions else "**No Additional Questions Generated**"}
    {chr(10).join(f"{i+len(session.internet_questions or [])+1}. {q}" for i, q in enumerate(generated_questions)) if generated_questions else ""}

    **Fixed Demographic Questions ({len(fixed_demographics)}) - Automatically Added:**
    {chr(10).join(f"{i+len(session.internet_questions or [])+len(generated_questions)+1}. {q}" for i, q in enumerate(fixed_demographics))}

    **Total Questions: {len(final_questions)}** ({len(session.internet_questions or [])} internet + {len(generated_questions)} generated + {len(fixed_demographics)} demographics)
    """
            specs_info = f"""- Internet questions: {len(session.internet_questions or [])} (all included)
    - Additional generated: {len(generated_questions)}
    - Fixed demographics: {len(fixed_demographics)} (automatically added)
    - Final total: {len(final_questions)}"""
            
        elif is_selection_mode:
            # S option: Generated questions + selected questions as extras + demographics (auto-added)
            selected_questions = session.questionnaire_responses.get('selected_questions', [])
            final_questions = generated_questions + selected_questions + fixed_demographics
            
            display_info = f"""**Generated Questions ({len(generated_questions)}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(generated_questions))}

    **Selected Internet Questions Added as Extras ({len(selected_questions)}):**
    {chr(10).join(f"{i+len(generated_questions)+1}. {q}" for i, q in enumerate(selected_questions))}

    **Fixed Demographic Questions ({len(fixed_demographics)}) - Automatically Added:**
    {chr(10).join(f"{i+len(generated_questions)+len(selected_questions)+1}. {q}" for i, q in enumerate(fixed_demographics))}

    **Total Questions: {len(final_questions)}** ({len(generated_questions)} generated + {len(selected_questions)} selected extras + {len(fixed_demographics)} demographics)
    """
            specs_info = f"""- Generated questions: {len(generated_questions)}
    - Selected extras: {len(selected_questions)}
    - Fixed demographics: {len(fixed_demographics)} (automatically added)
    - Final total: {len(final_questions)}"""
            
        else:
            # A option: Only generated questions + demographics (auto-added)
            final_questions = generated_questions + fixed_demographics
            
            display_info = f"""**Generated Questions ({len(generated_questions)}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(generated_questions))}

    **Fixed Demographic Questions ({len(fixed_demographics)}) - Automatically Added:**
    {chr(10).join(f"{i+len(generated_questions)+1}. {q}" for i, q in enumerate(fixed_demographics))}

    **Total Questions: {len(final_questions)}** ({len(generated_questions)} generated + {len(fixed_demographics)} demographics)
    """
            specs_info = f"""- Generated questions: {len(generated_questions)}
    - Fixed demographics: {len(fixed_demographics)} (automatically added)
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

    **Note:** The 5 demographic questions are automatically included in every survey and cannot be modified.

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
        """FIXED: Store accepted questions ensuring polling questions are included"""
        
        # Check if we have questions from different sources
        existing_count = len(session.questions) if session.questions else 0
        
        # If we have user-selected polling questions, make sure they're in the final questions
        if (hasattr(session, 'user_selected_questions') and 
            session.user_selected_questions and 
            existing_count == 0):
            
            # Convert polling questions to simple list
            polling_questions = [q['question'] for q in session.user_selected_questions]
            
            # Add demographics
            fixed_demographics = [
                "What is your age?",
                "What is your gender?",
                "What is your highest level of education?",
                "What is your annual household income range?",
                "In which city/region do you currently live?"
            ]
            
            # Combine polling questions with demographics
            session.questions = polling_questions + fixed_demographics
            existing_count = len(session.questions)
            
            logger.info(f"Added {len(polling_questions)} polling questions + {len(fixed_demographics)} demographics = {existing_count} total")
        
        # If still no questions, generate fallback
        if existing_count < 3:
            logger.info("Generating fallback questions as backup")
            fallback_questions = [
                "How satisfied are you with your overall experience?",
                "How would you rate the quality of service?",
                "How likely are you to recommend this to others?",
                "What factors are most important to you?",
                "How often do you use this service?",
                "What improvements would you suggest?",
                "How satisfied are you with the value for money?",
                "What is your age group?"
            ]
            
            if not session.questions:
                session.questions = fallback_questions
            else:
                # Add fallback questions to existing ones
                session.questions.extend(fallback_questions[:max(0, 8 - existing_count)])
        
        return f"""✅ **Questions Accepted ({len(session.questions)} questions)**

Would you like to add your own custom questions before proceeding to testing?

**Options:**
- **A** (Add Custom) - Enter your own additional questions
- **T** (Test Now) - Proceed directly to synthetic testing with current questions
- **R** (Review) - Review the current question list again"""
    
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
            
            # Store the feedback for potential regeneration
            session.__dict__['last_synthetic_feedback'] = synthetic_feedback
            
            return f"""
    🧪 **Testing Questionnaire with Synthetic Respondents**

    Running simulation with 5 diverse synthetic respondents matching your target population...

    **Testing {len(all_test_questions)} total questions**
    {breakdown_info}

    {synthetic_feedback}

    ---

    **Review the feedback above. What would you like to do?**
    - **Y** (Yes) - Finalize and export complete research package
    - **N** (No) - Make additional modifications to questionnaire
    - **F** (Fix Issues) - Regenerate questions based on synthetic feedback
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

    **Review these results. What would you like to do?**
    - **Y** (Yes) - Finalize and export complete research package
    - **N** (No) - Make additional modifications to questionnaire
    - **F** (Fix Issues) - Regenerate questions based on feedback
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
        """Generate realistic synthetic respondent feedback using AI for all questions - concise format"""
        
        questions_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(all_questions))
        
        prompt = f"""
    You are simulating 5 different synthetic respondents testing a survey questionnaire. 

    Research Topic: {session.research_topic}
    Target Population: {session.target_population}
    Total Questions: {len(all_questions)}

    Questions to test:
    {questions_text}

    For each respondent, provide EXACTLY one short line for each of these 5 points:
    1. Demographics: (age, background - one line)
    2. Completion time: (one line only)
    3. Confusion/issues: (one line only, or "None")
    4. Suggestions: (one line only, or "None") 
    5. Overall feedback: (one line only)

    Keep each line under 15 words. Be realistic about potential issues.

    Format as:
    **Respondent 1:** [age/background]
    - Time: [completion time]
    - Issues: [confusion or "None"]
    - Suggestions: [improvements or "None"]
    - Overall: [brief feedback]

    Create 5 diverse respondents. Total response under 200 words.
    """
        
        try:
            response = await self.llm.ask(prompt, temperature=0.8)
            cleaned_response = remove_chinese_and_punct(str(response))
            return cleaned_response
        except Exception as e:
            logger.error(f"Error generating synthetic feedback: {e}")
            return """
    **Respondent 1:** Age 25, Tech worker
    - Time: 7 minutes
    - Issues: Rating scale needs clearer labels
    - Suggestions: Add "Not Applicable" options
    - Overall: Questions are clear but need minor improvements

    **Respondent 2:** Age 35, Parent
    - Time: 11 minutes 
    - Issues: Some technical terms unclear
    - Suggestions: Simplify language for broader audience
    - Overall: Good flow but vocabulary too complex

    **Respondent 3:** Age 45, Manager
    - Time: 9 minutes
    - Issues: None
    - Suggestions: Add progress indicator
    - Overall: Professional and comprehensive

    **Respondent 4:** Age 28, Student
    - Time: 8 minutes
    - Issues: Missing mobile-friendly options
    - Suggestions: Test on mobile devices
    - Overall: Content good, format needs work

    **Respondent 5:** Age 52, Retiree  
    - Time: 15 minutes
    - Issues: Font size and button clarity
    - Suggestions: Larger text and buttons
    - Overall: Accessible design needed
    """
    
    async def _revise_questions(self, session: ResearchDesign) -> str:
        """Rephrase existing questions in different words - demographics remain unchanged"""
        if not session.questions:
            return "No questions available to revise. Please generate questions first."
        
        # Separate demographics from other questions - demographics are never revised
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
            return "Only demographic questions found. Demographics are fixed and cannot be revised."
        
        # Rephrase non-demographic questions only
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
    - DO NOT modify or include demographic questions

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
                    if not clean_line.endswith('?') and ')' not in clean_line:
                        clean_line += '?'
                    rephrased_questions.append(clean_line)
            
            # Ensure we have the right number of questions
            if len(rephrased_questions) < len(questions_to_rephrase):
                # Fill missing questions
                for i in range(len(rephrased_questions), len(questions_to_rephrase)):
                    rephrased_questions.append(questions_to_rephrase[i])
            elif len(rephrased_questions) > len(questions_to_rephrase):
                rephrased_questions = rephrased_questions[:len(questions_to_rephrase)]
            
            # Combine rephrased questions with unchanged demographics at the end
            session.questions = rephrased_questions + demographic_questions
            
            return f"""
    ✏️ **Questions Revised**

    **Rephrased Questions ({len(rephrased_questions)}):**
    {chr(10).join(f"{i+1}. {q}" for i, q in enumerate(rephrased_questions))}

    **Fixed Demographics ({len(demographic_questions)}) - Unchanged:**
    {chr(10).join(f"{i+len(rephrased_questions)+1}. {q}" for i, q in enumerate(demographic_questions))}

    **Total Questions: {len(session.questions)}**

    **Note:** Demographic questions remain fixed and unchanged as they are standardized.

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
    music_context = "thinking"  # Default music context
    
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
        
        # Detect music context based on message content
        message_lower = message.lower()
        if any(keyword in message_lower for keyword in ['research', 'study', 'questionnaire', 'survey']):
            music_context = "research"
        elif urls:
            music_context = "browsing"
        else:
            music_context = "thinking"
        
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
                        music_context = "browsing"  # Switch to browsing music
                        
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
            # No URL detected - use thinking music
            music_context = "thinking"
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
            "screenshot_validated": screenshot_base64 is not None,
            "music_context": music_context  # Add music context to response
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
            "screenshot_validated": False,
            "music_context": music_context
        }
    
    except Exception as e:
        error_msg = f"Error during agent execution: {e}"
        print(error_msg)
        save_comprehensive_response(message, error_msg, is_error=True)
        return {
            "response": error_msg,
            "base64_image": None,
            "source_url": detected_url,
            "screenshot_validated": False,
            "music_context": music_context
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
        self._enhanced_extractor = None
        # Configure CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        def _get_enhanced_extractor(self):
            """Get or create enhanced question extractor with LLM access"""
            if self._enhanced_extractor is None:
                llm_instance = getattr(self.agent, 'llm', None) if self.agent else None
                self._enhanced_extractor = QuestionExtractor(llm_instance)
            return self._enhanced_extractor

        # Initialize Manus agent on startup
        @self.app.on_event("startup")
        async def startup_event():
            logger.info("Application startup: Initializing Manus agent...")
            try:
                config_instance = Config()
                config = config_instance._config
                
                llm_instance = LLM(
                    model_name="Qwen/Qwen-7B-Chat",
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
                
                # ENHANCED: Initialize research workflow with browser tool for screenshots
                self.research_workflow = ResearchWorkflow(llm_instance, ui_instance=self)
                
                # CRITICAL: Share the browser tool with research workflow for polling screenshots
                self.research_workflow.browser_tool = browser_use_tool
                
                self.patch_agent_methods()
                logger.info("Manus agent and Research Workflow initialized successfully with browser tool sharing.")
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

        @self.app.get("/api/available-polls")
        async def get_available_polls():
            """Get list of available polling sources"""
            try:
                active_polls = PollingSiteConfig.get_active_polls()
                all_polls = PollingSiteConfig.get_all_polls()
                
                return JSONResponse({
                    "active_polls": active_polls,
                    "all_polls": all_polls,
                    "total_active": len(active_polls),
                    "total_available": len(all_polls)
                })
            except Exception as e:
                logger.error(f"Error getting available polls: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error getting polls: {str(e)}"}
                )

        @self.app.post("/api/message")
        async def handle_message(request: UserMessage):
            try:
                if not self.agent:
                    return JSONResponse(
                        status_code=500,
                        content={"response": "Agent not initialized", "status": "error"}
                    )

                session_id = request.research_session_id or "default_research_session"
                logger.info(f"HTTP processing message for session {session_id}: '{request.content[:50]}...'")
                
                # Check if we have an active research session first
                if session_id in self.research_workflow.active_sessions:
                    session = self.research_workflow.active_sessions[session_id]
                    slideshow_data = None
                    ui_selection_data = None
                    
                    # Handle poll selection JSON input
                    if session.__dict__.get('awaiting_poll_selection', False):
                        logger.info("HTTP: Session is awaiting poll selection")
                        try:
                            # Parse JSON input for poll selection
                            if request.content.strip().startswith('{'):
                                import json
                                selection_data = json.loads(request.content)
                                if 'selected_polls' in selection_data:
                                    logger.info(f"HTTP: Processing poll selection: {selection_data['selected_polls']}")
                                    
                                    # Process poll selection
                                    response_content = await self.research_workflow._handle_poll_selection(
                                        session_id, selection_data['selected_polls']
                                    )
                                    
                                    # Clear poll selection flags to prevent re-popup
                                    session.__dict__['awaiting_poll_selection'] = False
                                    session.__dict__['show_poll_selection'] = False
                                    session.__dict__['poll_selection_completed'] = True
                                    
                                    # Check for UI selection data AFTER processing
                                    if (hasattr(session, '__dict__') and 
                                        'ui_selection_data' in session.__dict__ and
                                        session.__dict__.get('trigger_question_selection_ui', False)):
                                        
                                        ui_selection_data = session.__dict__['ui_selection_data']
                                        session.__dict__['trigger_question_selection_ui'] = False
                                        logger.info(f"HTTP: Found UI selection data with {len(ui_selection_data.get('questions', []))} questions")
                                    
                                    # Check for slideshow data
                                    if hasattr(session, 'screenshots') and session.screenshots is not None:
                                        slideshow_data = {
                                            "screenshots": session.screenshots,
                                            "total_count": len(session.screenshots),
                                            "research_topic": session.research_topic
                                        }
                                    
                                    result = {
                                        "response": response_content,
                                        "status": "success",
                                        "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                                        "session_id": session_id
                                    }
                                    
                                    # Add UI selection data to HTTP response
                                    if ui_selection_data:
                                        result["ui_selection_data"] = ui_selection_data
                                        result["show_question_selection"] = True
                                        logger.info("HTTP: Added UI selection data to response")
                                    
                                    # Add slideshow data
                                    if slideshow_data and slideshow_data["screenshots"]:
                                        result["slideshow_data"] = slideshow_data
                                        result["base64_image"] = slideshow_data["screenshots"][0]["screenshot"]
                                        result["image_url"] = slideshow_data["screenshots"][0]["url"]
                                        result["image_title"] = slideshow_data["screenshots"][0]["title"]
                                    
                                    return JSONResponse(result)
                        except Exception as e:
                            logger.error(f"HTTP: Error processing poll selection: {e}")
                    
                    # Process the research input
                    logger.info("HTTP: Processing regular research input")
                    response_content = await self.research_workflow.process_research_input(
                        session_id, request.content
                    )
                    
                    # CRITICAL: Check if response indicates poll selection is needed
                    if response_content == "POLL_SELECTION_NEEDED":
                        logger.info("HTTP: Poll selection needed - returning poll selection response")
                        available_polls = PollingSiteConfig.get_active_polls(session.research_topic)
                        if available_polls:
                            # Check if this is a rebrowse situation
                            is_rebrowse = session.rebrowse_count > 0
                            rebrowse_info = f" (Rebrowse Attempt {session.rebrowse_count}/4)" if is_rebrowse else ""
                            
                            logger.info(f"HTTP: Returning poll selection UI - is_rebrowse: {is_rebrowse}")
                            
                            return JSONResponse({
                                "response": (
                                    f"🔄 **Select Polling Sites to Search{rebrowse_info}**\n\n"
                                    "Please select which polling organizations you'd like to search for questions.\n"
                                    "Use the poll selection panel below. Click **Start Polling Search** when ready."
                                ),
                                "status": "success",
                                "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                                "session_id": session_id,
                                "available_polls": available_polls,
                                "show_poll_selection": True,
                                "is_rebrowse": is_rebrowse
                            })
                    
                    # Check if we have screenshots to include
                    if hasattr(session, 'screenshots') and session.screenshots is not None:
                        slideshow_data = {
                            "screenshots": session.screenshots,
                            "total_count": len(session.screenshots),
                            "research_topic": session.research_topic
                        }
                    
                    # Check for UI selection data after processing
                    if (hasattr(session, '__dict__') and 
                        'ui_selection_data' in session.__dict__ and
                        session.__dict__.get('trigger_question_selection_ui', False)):
                        
                        ui_selection_data = session.__dict__['ui_selection_data']
                        session.__dict__['trigger_question_selection_ui'] = False
                        logger.info(f"HTTP: Sending UI selection data with {len(ui_selection_data.get('questions', []))} questions")
                    
                    # Prepare the result
                    result = {
                        "response": response_content,
                        "status": "success",
                        "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                        "session_id": session_id
                    }
                    
                    # Only show poll selection if NOT already completed and actually needed
                    if (hasattr(session, '__dict__') and 
                        session.__dict__.get('show_poll_selection', False) and
                        not session.__dict__.get('poll_selection_completed', False)):
                        
                        available_polls = session.__dict__.get('available_polls', {})
                        if available_polls:
                            result["available_polls"] = available_polls
                            result["show_poll_selection"] = True

                    # Add UI selection data if available
                    if ui_selection_data:
                        result["ui_selection_data"] = ui_selection_data
                        result["show_question_selection"] = True
                        logger.info("HTTP: Added UI selection data to response")
                    
                    # Add slideshow data if we have screenshots
                    if slideshow_data and slideshow_data["screenshots"]:
                        result["slideshow_data"] = slideshow_data
                        result["base64_image"] = slideshow_data["screenshots"][0]["screenshot"]
                        result["image_url"] = slideshow_data["screenshots"][0]["url"]
                        result["image_title"] = slideshow_data["screenshots"][0]["title"]
                    
                    return JSONResponse(result)

                # Handle non-research sessions
                action_type = request.action_type
                if not action_type:
                    intent = detect_user_intent(request.content)
                    action_type = intent.value

                # Handle different action types
                if action_type == UserAction.BUILD_QUESTIONNAIRE.value:
                    # Start new research session
                    session_id = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
                    logger.info(f"HTTP: Starting new research session: {session_id}")
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
                        
                        if source_url:
                            result["source_url"] = source_url
                            result["image_url"] = source_url
                            
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
                logger.error(f"HTTP: Error in handle_message: {str(e)}", exc_info=True)
                error_response = f"Server error: {str(e)}"
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
        """Process a user message via WebSocket with COMPLETE poll selection and rebrowse handling"""
        try:
            if not self.agent:
                await self.broadcast_message("error", {"message": "Agent not initialized"})
                return

            logger.info(f"WebSocket processing message for session {session_id}: '{user_message[:50]}...'")

            # Check if we have an active research session first
            if session_id in self.research_workflow.active_sessions:
                session = self.research_workflow.active_sessions[session_id]
                
                # PRIORITY 1: Handle poll selection with polling site screenshots
                if session.__dict__.get('awaiting_poll_selection', False):
                    logger.info("WebSocket: Session is awaiting poll selection")
                    try:
                        # Parse JSON input for poll selection
                        if user_message.strip().startswith('{'):
                            import json
                            selection_data = json.loads(user_message)
                            if 'selected_polls' in selection_data:
                                logger.info(f"WebSocket: Processing poll selection: {selection_data['selected_polls']}")
                                
                                # Process poll selection WITH screenshots
                                response_content = await self.research_workflow._handle_poll_selection(
                                    session_id, selection_data['selected_polls']
                                )
                                
                                # Clear poll selection flags immediately
                                session.__dict__['awaiting_poll_selection'] = False
                                session.__dict__['show_poll_selection'] = False
                                session.__dict__['poll_selection_completed'] = True
                                
                                # Handle UI selection data and screenshots
                                ui_selection_data = None
                                slideshow_data = None
                                
                                if (hasattr(session, '__dict__') and 
                                    'ui_selection_data' in session.__dict__ and
                                    session.__dict__.get('trigger_question_selection_ui', False)):
                                    
                                    ui_selection_data = session.__dict__['ui_selection_data']
                                    session.__dict__['trigger_question_selection_ui'] = False
                                    logger.info(f"WebSocket: Broadcasting UI selection data with {len(ui_selection_data.get('questions', []))} questions")
                                
                                # Check for slideshow data
                                screenshots = getattr(session, 'screenshots', None)
                                if screenshots is not None and len(screenshots) > 0:
                                    slideshow_data = {
                                        "screenshots": screenshots,
                                        "total_count": len(screenshots),
                                        "research_topic": session.research_topic,
                                        "is_polling_phase": True,
                                        "phase_name": "Selected Polling Organizations"
                                    }
                                    
                                    # Add polling metadata if available
                                    if session.__dict__.get('polling_screenshots_count', 0) > 0:
                                        slideshow_data["polling_screenshots_count"] = session.__dict__['polling_screenshots_count']
                                        slideshow_data["description"] = f"Overview of {session.__dict__['polling_screenshots_count']} polling organizations"
                                    
                                    logger.info(f"WebSocket: Broadcasting slideshow with {len(screenshots)} screenshots")
                                
                                # Prepare response message
                                message_data = {
                                    "content": response_content,
                                    "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                                    "session_id": session_id
                                }
                                
                                # Add UI selection data if available
                                if ui_selection_data:
                                    message_data["ui_selection_data"] = ui_selection_data
                                    message_data["show_question_selection"] = True
                                    logger.info("WebSocket: Added UI selection data to message")
                                
                                # Add slideshow data if available
                                if slideshow_data:
                                    message_data["slideshow_data"] = slideshow_data
                                    if slideshow_data["screenshots"]:
                                        message_data["base64_image"] = slideshow_data["screenshots"][0]["screenshot"]
                                        message_data["image_url"] = slideshow_data["screenshots"][0]["url"]
                                        message_data["image_title"] = slideshow_data["screenshots"][0]["title"]
                                
                                await self.broadcast_message("agent_message", message_data)
                                
                                # Send separate slideshow update
                                if slideshow_data:
                                    await self.broadcast_message("slideshow_data", slideshow_data)
                                    
                                    # Send browser state update
                                    await self.broadcast_message("browser_state", {
                                        "base64_image": slideshow_data["screenshots"][0]["screenshot"],
                                        "url": slideshow_data["screenshots"][0]["url"],
                                        "title": slideshow_data["screenshots"][0]["title"],
                                        "source_url": slideshow_data["screenshots"][0]["url"],
                                        "is_polling_site": True
                                    })
                                
                                return
                    except Exception as e:
                        logger.error(f"WebSocket: Error processing poll selection: {e}")
                
                # Only show poll selection popup if NOT already handled
                if (session.__dict__.get('show_poll_selection', False) and 
                    not session.__dict__.get('awaiting_poll_selection', False) and
                    not session.__dict__.get('poll_selection_completed', False)):
                    
                    available_polls = session.__dict__.get('available_polls', {})
                    if available_polls:
                        # Check if this is a rebrowse situation
                        is_rebrowse = session.rebrowse_count > 0
                        rebrowse_info = f" (Rebrowse Attempt {session.rebrowse_count}/4)" if is_rebrowse else ""
                        
                        await self.broadcast_message("agent_message", {
                            "content": (
                                f"🔄 **Select Polling Sites to Search{rebrowse_info}**\n\n"
                                "Please select which polling organizations you'd like to search for questions.\n"
                                "Use the poll selection panel below. Click **Start Polling Search** when ready."
                            ),
                            "available_polls": available_polls,
                            "show_poll_selection": True,
                            "session_id": session_id,
                            "action_type": "poll_selection",
                            "is_rebrowse": is_rebrowse
                        })
                        # Set awaiting flag but DON'T clear show flag yet
                        session.__dict__['awaiting_poll_selection'] = True
                        return
                
                # ENHANCED: Handle design input completion (when research design is generated)
                if (session.stage == ResearchStage.DESIGN_INPUT and 
                    hasattr(session, 'user_responses') and
                    session.user_responses is not None and
                    'target_population' not in session.user_responses):
                    
                    try:
                        # This is the final design input step - process it
                        response = await self.research_workflow.process_research_input(session_id, user_message)
                        
                        # AFTER processing, check if research screenshots were generated
                        if (hasattr(session, '__dict__') and 
                            session.__dict__.get('has_research_screenshots', False)):
                            
                            research_screenshots = getattr(session, 'research_screenshots', None) or []
                            if research_screenshots:
                                logger.info(f"Broadcasting research design screenshots: {len(research_screenshots)} screenshots")
                                
                                # Send research slideshow data to frontend
                                await self.broadcast_message("slideshow_data", {
                                    "screenshots": research_screenshots,
                                    "total_count": len(research_screenshots),
                                    "research_topic": getattr(session, 'research_topic', 'Research Topic'),
                                    "is_research_phase": True,
                                    "phase_name": "Research Design - Related Studies"
                                })
                                
                                # Send the first research screenshot to browser view
                                if research_screenshots:
                                    await self.broadcast_message("browser_state", {
                                        "base64_image": research_screenshots[0]['screenshot'],
                                        "url": research_screenshots[0]['url'],
                                        "title": research_screenshots[0]['title'],
                                        "source_url": research_screenshots[0]['url']
                                    })
                        
                        # Check if poll selection is needed
                        if response == "POLL_SELECTION_NEEDED":
                            # Trigger poll selection UI
                            available_polls = session.__dict__.get('available_polls', {})
                            if available_polls:
                                # Check if this is a rebrowse situation
                                is_rebrowse = session.rebrowse_count > 0
                                rebrowse_info = f" (Rebrowse Attempt {session.rebrowse_count}/4)" if is_rebrowse else ""
                                
                                await self.broadcast_message("agent_message", {
                                    "content": (
                                        f"🔄 **Select Polling Sites to Search{rebrowse_info}**\n\n"
                                        "Please select which polling organizations you'd like to search for questions.\n"
                                        "Use the poll selection panel below. Click **Start Polling Search** when ready."
                                    ),
                                    "available_polls": available_polls,
                                    "show_poll_selection": True,
                                    "session_id": session_id,
                                    "action_type": "poll_selection",
                                    "is_rebrowse": is_rebrowse
                                })
                                return
                        
                        # Send the main response
                        await self.broadcast_message("agent_message", {
                            "content": response,
                            "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                            "session_id": session_id
                        })
                        return
                        
                    except Exception as e:
                        logger.warning(f"Could not process design input with research screenshots: {e}")
                
                # ENHANCED: Handle research design approval (Y response) with research slideshow
                elif (session.stage == ResearchStage.DESIGN_REVIEW and 
                    user_message.upper().strip() == 'Y'):
                    try:
                        # Process the research input which will capture research screenshots
                        response = await self.research_workflow.process_research_input(session_id, user_message)
                        
                        # Check if poll selection is needed
                        if response == "POLL_SELECTION_NEEDED":
                            # Trigger poll selection UI
                            available_polls = session.__dict__.get('available_polls', {})
                            if available_polls:
                                # Check if this is a rebrowse situation
                                is_rebrowse = session.rebrowse_count > 0
                                rebrowse_info = f" (Rebrowse Attempt {session.rebrowse_count}/4)" if is_rebrowse else ""
                                
                                await self.broadcast_message("agent_message", {
                                    "content": (
                                        f"🔄 **Select Polling Sites to Search{rebrowse_info}**\n\n"
                                        "Please select which polling organizations you'd like to search for questions.\n"
                                        "Use the poll selection panel below. Click **Start Polling Search** when ready."
                                    ),
                                    "available_polls": available_polls,
                                    "show_poll_selection": True,
                                    "session_id": session_id,
                                    "action_type": "poll_selection",
                                    "is_rebrowse": is_rebrowse
                                })
                                return
                        
                        # Check if we have research screenshots to display FIRST
                        research_screenshots = getattr(session, 'research_screenshots', None)
                        if research_screenshots:
                            logger.info(f"Broadcasting research slideshow with {len(research_screenshots)} screenshots")
                            
                            # Send research slideshow data to frontend
                            await self.broadcast_message("slideshow_data", {
                                "screenshots": research_screenshots,
                                "total_count": len(research_screenshots),
                                "research_topic": getattr(session, 'research_topic', 'Research Topic'),
                                "is_research_phase": True,  # Flag to indicate this is research phase
                                "phase_name": "Research Design"
                            })
                            
                            # Send the first research screenshot to browser view
                            if research_screenshots:
                                await self.broadcast_message("browser_state", {
                                    "base64_image": research_screenshots[0]['screenshot'],
                                    "url": research_screenshots[0]['url'],
                                    "title": research_screenshots[0]['title'],
                                    "source_url": research_screenshots[0]['url']
                                })
                        
                        # After processing, check if we NOW have internet search screenshots too
                        screenshots = getattr(session, 'screenshots', None)
                        if screenshots is not None:
                            # Count research vs internet screenshots
                            research_count = len(research_screenshots) if research_screenshots else 0
                            total_count = len(screenshots)
                            internet_count = total_count - research_count
                            
                            if internet_count > 0:
                                logger.info(f"Broadcasting combined slideshow: {research_count} research + {internet_count} internet = {total_count} total")
                                
                                # Send combined slideshow data to frontend
                                await self.broadcast_message("slideshow_data", {
                                    "screenshots": screenshots,
                                    "total_count": total_count,
                                    "research_topic": getattr(session, 'research_topic', 'Research Topic'),
                                    "is_combined_phase": True,  # Flag for combined research + internet
                                    "research_count": research_count,
                                    "internet_count": internet_count
                                })
                                
                                # Show the first internet search screenshot (if available)
                                if internet_count > 0:
                                    first_internet_index = research_count  # First internet screenshot
                                    if first_internet_index < len(screenshots):
                                        await self.broadcast_message("browser_state", {
                                            "base64_image": screenshots[first_internet_index]['screenshot'],
                                            "url": screenshots[first_internet_index]['url'],
                                            "title": screenshots[first_internet_index]['title'],
                                            "source_url": screenshots[first_internet_index]['url']
                                        })
                        
                        # Check for UI selection data AFTER processing
                        ui_selection_data = None
                        if (hasattr(session, '__dict__') and 
                            'ui_selection_data' in session.__dict__ and
                            session.__dict__.get('trigger_question_selection_ui', False)):
                            
                            ui_selection_data = session.__dict__['ui_selection_data']
                            session.__dict__['trigger_question_selection_ui'] = False
                            logger.info(f"Broadcasting UI selection data with {len(ui_selection_data.get('questions', []))} questions")
                        
                        # Send the main response with UI selection data if available
                        message_data = {
                            "content": response,
                            "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                            "session_id": session_id
                        }
                        
                        # Add UI selection data if available
                        if ui_selection_data:
                            message_data["ui_selection_data"] = ui_selection_data
                            message_data["show_question_selection"] = True
                            logger.info("Added UI selection data to agent message")
                        
                        await self.broadcast_message("agent_message", message_data)
                        return
                        
                    except Exception as e:
                        logger.warning(f"Could not process research design approval with slideshow: {e}")
                
                # ENHANCED: Handle initial search (after research design) with slideshow
                elif session.stage == ResearchStage.DATABASE_SEARCH and not hasattr(session, '_database_search_started'):
                    try:
                        # Mark that database search has started to avoid duplicate processing
                        session._database_search_started = True
                        
                        # Store screenshots count before search - FIXED null check
                        screenshots = getattr(session, 'screenshots', None)
                        old_screenshot_count = len(screenshots) if screenshots is not None else 0
                        
                        # Process the search which will capture screenshots of found URLs
                        response = await self.research_workflow.process_research_input(session_id, user_message)
                        
                        # Check if poll selection is needed
                        if response == "POLL_SELECTION_NEEDED":
                            # Trigger poll selection UI
                            available_polls = session.__dict__.get('available_polls', {})
                            if available_polls:
                                # Check if this is a rebrowse situation
                                is_rebrowse = session.rebrowse_count > 0
                                rebrowse_info = f" (Rebrowse Attempt {session.rebrowse_count}/4)" if is_rebrowse else ""
                                
                                await self.broadcast_message("agent_message", {
                                    "content": (
                                        f"🔄 **Select Polling Sites to Search{rebrowse_info}**\n\n"
                                        "Please select which polling organizations you'd like to search for questions.\n"
                                        "Use the poll selection panel below. Click **Start Polling Search** when ready."
                                    ),
                                    "available_polls": available_polls,
                                    "show_poll_selection": True,
                                    "session_id": session_id,
                                    "action_type": "poll_selection",
                                    "is_rebrowse": is_rebrowse
                                })
                                return
                        
                        # Check for UI selection data AFTER processing
                        ui_selection_data = None
                        if (hasattr(session, '__dict__') and 
                            'ui_selection_data' in session.__dict__ and
                            session.__dict__.get('trigger_question_selection_ui', False)):
                            
                            ui_selection_data = session.__dict__['ui_selection_data']
                            session.__dict__['trigger_question_selection_ui'] = False
                            logger.info(f"Broadcasting UI selection data with {len(ui_selection_data.get('questions', []))} questions")
                        
                        # After processing, check if we have NEW screenshots to display - FIXED null checks
                        screenshots_after = getattr(session, 'screenshots', None)
                        if screenshots_after is not None:
                            new_screenshot_count = len(screenshots_after)
                            new_screenshots_added = new_screenshot_count - old_screenshot_count
                            
                            if new_screenshots_added > 0:
                                logger.info(f"Broadcasting initial internet search slideshow with {new_screenshots_added} new screenshots")
                                
                                # Send slideshow data to frontend
                                await self.broadcast_message("slideshow_data", {
                                    "screenshots": screenshots_after,
                                    "total_count": len(screenshots_after),
                                    "research_topic": getattr(session, 'research_topic', 'Research Topic'),
                                    "is_update": old_screenshot_count > 0,  # True if this is an update
                                    "new_screenshots_added": new_screenshots_added
                                })
                                
                                # Also send the first NEW screenshot to browser view
                                if new_screenshots_added > 0 and len(screenshots_after) > old_screenshot_count:
                                    # Show the first new screenshot (skip research screenshots if any)
                                    first_new_index = old_screenshot_count
                                    if first_new_index < len(screenshots_after):
                                        await self.broadcast_message("browser_state", {
                                            "base64_image": screenshots_after[first_new_index]['screenshot'],
                                            "url": screenshots_after[first_new_index]['url'],
                                            "title": screenshots_after[first_new_index]['title'],
                                            "source_url": screenshots_after[first_new_index]['url']
                                        })
                        
                        # Send the main response with UI selection data if available
                        message_data = {
                            "content": response,
                            "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                            "session_id": session_id
                        }
                        
                        # Add UI selection data if available
                        if ui_selection_data:
                            message_data["ui_selection_data"] = ui_selection_data
                            message_data["show_question_selection"] = True
                            logger.info("Added UI selection data to agent message")
                        
                        await self.broadcast_message("agent_message", message_data)
                        return
                        
                    except Exception as e:
                        logger.warning(f"Could not process initial search with screenshots: {e}")
                
                # ENHANCED: Handle rebrowse (R response) with updated slideshow
                elif session.stage == ResearchStage.DECISION_POINT and user_message.upper().strip() == 'R':
                    try:
                        # Store screenshots count before rebrowse - FIXED null check
                        screenshots = getattr(session, 'screenshots', None)
                        old_screenshot_count = len(screenshots) if screenshots is not None else 0
                        
                        # Process the rebrowse which will capture additional screenshots
                        response = await self.research_workflow.process_research_input(session_id, user_message)
                        
                        # CRITICAL: Check if response indicates poll selection is needed
                        if response == "POLL_SELECTION_NEEDED":
                            logger.info("WebSocket: Rebrowse triggered poll selection - showing poll selection UI")
                            available_polls = session.__dict__.get('available_polls', {})
                            if available_polls:
                                # This IS a rebrowse situation
                                is_rebrowse = True
                                rebrowse_info = f" (Rebrowse Attempt {session.rebrowse_count}/4)"
                                
                                await self.broadcast_message("agent_message", {
                                    "content": (
                                        f"🔄 **Select Polling Sites to Search{rebrowse_info}**\n\n"
                                        "Please select which polling organizations you'd like to search for questions.\n"
                                        "Use the poll selection panel below. Click **Start Polling Search** when ready."
                                    ),
                                    "available_polls": available_polls,
                                    "show_poll_selection": True,
                                    "session_id": session_id,
                                    "action_type": "poll_selection",
                                    "is_rebrowse": is_rebrowse
                                })
                                return
                        
                        # Check for UI selection data AFTER processing
                        ui_selection_data = None
                        if (hasattr(session, '__dict__') and 
                            'ui_selection_data' in session.__dict__ and
                            session.__dict__.get('trigger_question_selection_ui', False)):
                            
                            ui_selection_data = session.__dict__['ui_selection_data']
                            session.__dict__['trigger_question_selection_ui'] = False
                            logger.info(f"Broadcasting updated UI selection data with {len(ui_selection_data.get('questions', []))} questions")
                        
                        # After processing, check if we have updated screenshots to display - FIXED null checks
                        screenshots_after = getattr(session, 'screenshots', None)
                        if screenshots_after is not None:
                            new_screenshot_count = len(screenshots_after)
                            new_screenshots_added = new_screenshot_count - old_screenshot_count
                            
                            if new_screenshots_added > 0:
                                logger.info(f"Broadcasting updated slideshow: {old_screenshot_count} -> {new_screenshot_count} screenshots (+{new_screenshots_added})")
                                
                                # Send updated slideshow data to frontend
                                await self.broadcast_message("slideshow_data", {
                                    "screenshots": screenshots_after,
                                    "total_count": len(screenshots_after),
                                    "research_topic": getattr(session, 'research_topic', 'Research Topic'),
                                    "is_update": True,  # Flag to indicate this is an update
                                    "new_screenshots_added": new_screenshots_added
                                })
                                
                                # Send the most recent screenshot to browser view (last added)
                                if new_screenshots_added > 0 and len(screenshots_after) > 0:
                                    latest_screenshot = screenshots_after[-1]  # Get the last (newest) screenshot
                                    await self.broadcast_message("browser_state", {
                                        "base64_image": latest_screenshot['screenshot'],
                                        "url": latest_screenshot['url'],
                                        "title": latest_screenshot['title'],
                                        "source_url": latest_screenshot['url']
                                    })
                        
                        # Send the main response with UI selection data if available
                        message_data = {
                            "content": response,
                            "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                            "session_id": session_id
                        }
                        
                        # Add UI selection data if available
                        if ui_selection_data:
                            message_data["ui_selection_data"] = ui_selection_data
                            message_data["show_question_selection"] = True
                            logger.info("Added updated UI selection data to agent message")
                        
                        await self.broadcast_message("agent_message", message_data)
                        return
                        
                    except Exception as e:
                        logger.warning(f"Could not process rebrowse with screenshots: {e}")
                
                # ENHANCED: Handle question selection responses that might trigger more rebrowsing - FIXED NULL CHECKS
                elif (session.stage == ResearchStage.DECISION_POINT and 
                    hasattr(session, 'awaiting_selection') and 
                    getattr(session, 'awaiting_selection', False)):
                    try:
                        # Store screenshots count before processing selection - FIXED null check
                        screenshots = getattr(session, 'screenshots', None)
                        old_screenshot_count = len(screenshots) if screenshots is not None else 0
                        
                        # Process the selection input
                        response = await self.research_workflow.process_research_input(session_id, user_message)
                        
                        # Check if poll selection is needed
                        if response == "POLL_SELECTION_NEEDED":
                            # Trigger poll selection UI
                            available_polls = session.__dict__.get('available_polls', {})
                            if available_polls:
                                # Check if this is a rebrowse situation
                                is_rebrowse = session.rebrowse_count > 0
                                rebrowse_info = f" (Rebrowse Attempt {session.rebrowse_count}/4)" if is_rebrowse else ""
                                
                                await self.broadcast_message("agent_message", {
                                    "content": (
                                        f"🔄 **Select Polling Sites to Search{rebrowse_info}**\n\n"
                                        "Please select which polling organizations you'd like to search for questions.\n"
                                        "Use the poll selection panel below. Click **Start Polling Search** when ready."
                                    ),
                                    "available_polls": available_polls,
                                    "show_poll_selection": True,
                                    "session_id": session_id,
                                    "action_type": "poll_selection",
                                    "is_rebrowse": is_rebrowse
                                })
                                return
                        
                        # Check for UI selection data AFTER processing
                        ui_selection_data = None
                        if (hasattr(session, '__dict__') and 
                            'ui_selection_data' in session.__dict__ and
                            session.__dict__.get('trigger_question_selection_ui', False)):
                            
                            ui_selection_data = session.__dict__['ui_selection_data']
                            session.__dict__['trigger_question_selection_ui'] = False
                            logger.info(f"Broadcasting selection UI data with {len(ui_selection_data.get('questions', []))} questions")
                        
                        # Check if screenshots were updated during selection processing - FIXED null checks
                        screenshots_after = getattr(session, 'screenshots', None)
                        if screenshots_after is not None:
                            new_screenshot_count = len(screenshots_after)
                            
                            # If new screenshots were added, update the slideshow
                            if new_screenshot_count > old_screenshot_count:
                                new_screenshots_added = new_screenshot_count - old_screenshot_count
                                logger.info(f"Selection processing added screenshots: {old_screenshot_count} -> {new_screenshot_count} (+{new_screenshots_added})")
                                
                                await self.broadcast_message("slideshow_data", {
                                    "screenshots": screenshots_after,
                                    "total_count": len(screenshots_after),
                                    "research_topic": getattr(session, 'research_topic', 'Research Topic'),
                                    "is_update": True,
                                    "new_screenshots_added": new_screenshots_added
                                })
                                
                                # Update browser view with latest screenshot
                                if len(screenshots_after) > 0:
                                    latest_screenshot = screenshots_after[-1]
                                    await self.broadcast_message("browser_state", {
                                        "base64_image": latest_screenshot['screenshot'],
                                        "url": latest_screenshot['url'],
                                        "title": latest_screenshot['title'],
                                        "source_url": latest_screenshot['url']
                                    })
                        
                        # Send the main response with UI selection data if available
                        message_data = {
                            "content": response,
                            "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                            "session_id": session_id
                        }
                        
                        # Add UI selection data if available
                        if ui_selection_data:
                            message_data["ui_selection_data"] = ui_selection_data
                            message_data["show_question_selection"] = True
                            logger.info("Added selection UI data to agent message")
                        
                        await self.broadcast_message("agent_message", message_data)
                        return
                        
                    except Exception as e:
                        logger.warning(f"Could not process selection with potential screenshots: {e}")
                
                # Regular research workflow processing for all other cases
                logger.info("WebSocket: Processing regular research input")
                response = await self.research_workflow.process_research_input(session_id, user_message)
                
                # CRITICAL: Check if response indicates poll selection is needed
                if response == "POLL_SELECTION_NEEDED":
                    logger.info("WebSocket: Regular processing triggered poll selection - showing poll selection UI")
                    available_polls = session.__dict__.get('available_polls', {})
                    if available_polls:
                        # Check if this is a rebrowse situation
                        is_rebrowse = session.rebrowse_count > 0
                        rebrowse_info = f" (Rebrowse Attempt {session.rebrowse_count}/4)" if is_rebrowse else ""
                        
                        await self.broadcast_message("agent_message", {
                            "content": (
                                f"🔄 **Select Polling Sites to Search{rebrowse_info}**\n\n"
                                "Please select which polling organizations you'd like to search for questions.\n"
                                "Use the poll selection panel below. Click **Start Polling Search** when ready."
                            ),
                            "available_polls": available_polls,
                            "show_poll_selection": True,
                            "session_id": session_id,
                            "action_type": "poll_selection",
                            "is_rebrowse": is_rebrowse
                        })
                        return
                
                # ALWAYS check for UI selection data after ANY processing
                ui_selection_data = None
                if (hasattr(session, '__dict__') and 
                    'ui_selection_data' in session.__dict__ and
                    session.__dict__.get('trigger_question_selection_ui', False)):
                    
                    ui_selection_data = session.__dict__['ui_selection_data']
                    session.__dict__['trigger_question_selection_ui'] = False
                    logger.info(f"Broadcasting general UI selection data with {len(ui_selection_data.get('questions', []))} questions")
                
                # Send the main response
                message_data = {
                    "content": response,
                    "action_type": UserAction.BUILD_QUESTIONNAIRE.value,
                    "session_id": session_id
                }
                
                # Add UI selection data if available
                if ui_selection_data:
                    message_data["ui_selection_data"] = ui_selection_data
                    message_data["show_question_selection"] = True
                    logger.info("Added general UI selection data to agent message")
                
                await self.broadcast_message("agent_message", message_data)
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
                "action_type": action_type if 'action_type' in locals() else None
            })
        except Exception as e:
            logger.error(f"WebSocket: Error processing message: {str(e)}", exc_info=True)
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

    async def broadcast_scraping_status(self, status: str, details: str = ""):
        """Broadcast scraping status to connected clients"""
        await self.broadcast_message("scraping_status", {
            "status": status,
            "details": details,
            "timestamp": time.time()
        })

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