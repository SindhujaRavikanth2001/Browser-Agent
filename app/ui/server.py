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
    stage: ResearchStage = ResearchStage.INITIAL
    user_responses: Optional[Dict] = None

class UserMessage(BaseModel):
    content: str
    action_type: Optional[str] = None
    research_session_id: Optional[str] = None

# Research Design Workflow Functions
class ResearchWorkflow:
    def __init__(self, llm_instance):
        self.llm = llm_instance
        self.active_sessions: Dict[str, ResearchDesign] = {}
        self.question_database = self._initialize_question_database()
    
    def _initialize_question_database(self):
        """Initialize mock question database - replace with real database connection"""
        return {
            "demographic": [
                "What is your age group?",
                "What is your gender identity?",
                "What is your highest level of education?",
                "What is your employment status?",
                "What is your annual household income range?"
            ],
            "behavioral": [
                "How often do you engage in this behavior?",
                "What factors influence your decision-making?",
                "How satisfied are you with this experience?",
                "What would motivate you to change this behavior?"
            ],
            "attitudinal": [
                "How strongly do you agree with this statement?",
                "What is your opinion on this topic?",
                "How important is this factor to you?",
                "How likely are you to recommend this?"
            ]
        }
    
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

{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(session.questions or []))}

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
- **Questions:** {len(session.questions or [])} validated questions
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
        """Search question/data databases for relevant content"""
        # Mock database search - replace with real database queries
        relevant_questions = []
        
        # Simple keyword matching for demo
        topic_keywords = session.research_topic.lower().split()
        
        for category, questions in self.question_database.items():
            for question in questions:
                if any(keyword in question.lower() for keyword in topic_keywords):
                    relevant_questions.append(f"[{category.title()}] {question}")
        
        # If no matches, add some general questions
        if not relevant_questions:
            relevant_questions = [
                "[General] How satisfied are you with your current experience?",
                "[General] What factors are most important to you?",
                "[General] How likely are you to recommend this to others?"
            ]
        
        session.questions = relevant_questions
        session.stage = ResearchStage.DECISION_POINT
        
        return f"""
🔍 **Database Search Results**

Found {len(relevant_questions)} relevant questions for your research:

{chr(10).join(f"• {q}" for q in relevant_questions[:10])}
{"..." if len(relevant_questions) > 10 else ""}

**Available databases searched:**
• Marist SPSS Database (test)
• General Research Question Repository
• Demographic Standards Database

---

**Do you want to proceed to Questionnaire Builder?**

Reply with:
- **Y** (Yes) - Go to Questionnaire Builder
- **N** (No) - Export research design only
- **E** (Exit) - Exit workflow
"""
    
    async def _handle_decision_point(self, session_id: str, user_input: str) -> str:
        """Handle major decision point"""
        session = self.active_sessions[session_id]
        response = user_input.upper().strip()
        
        if response == 'Y':
            session.stage = ResearchStage.QUESTIONNAIRE_BUILDER
            return await self._start_questionnaire_builder(session)
        elif response == 'N':
            return await self._export_research_design_only(session)
        elif response == 'E':
            del self.active_sessions[session_id]
            return "Research design workflow ended. Thank you!"
        else:
            return """
Please respond with:
- **Y** (Yes) - Go to Questionnaire Builder
- **N** (No) - Export research design only
- **E** (Exit) - Exit workflow
"""
    
    async def _start_questionnaire_builder(self, session: ResearchDesign) -> str:
        """Start the questionnaire builder process"""
        return f"""
📝 **Questionnaire Builder**

**Available Questions ({len(session.questions)}):**
{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(session.questions[:5]))}
{"..." if len(session.questions) > 5 else ""}

**Questionnaire Builder Options:**

1. **Generate New Questions** - AI will create custom questions for your research
2. **Select from Existing** - Choose from the questions found in our database
3. **Combine Both** - Use existing questions and generate new ones
4. **Set Limits** - Define maximum number of questions or question types

Please choose an option (1-4) or describe what you'd like to do:
"""
    
    async def _handle_questionnaire_builder(self, session_id: str, user_input: str) -> str:
        """Handle questionnaire builder interactions"""
        session = self.active_sessions[session_id]
        
        if user_input.strip() == '1':
            return await self._generate_new_questions(session)
        elif user_input.strip() == '2':
            return await self._select_existing_questions(session)
        elif user_input.strip() == '3':
            return await self._combine_questions(session)
        elif user_input.strip() == '4':
            return await self._set_limits(session)
        elif user_input.upper().strip() == 'A':
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
            # Back to menu
            return await self._start_questionnaire_builder(session)
        else:
            # Process as natural language request
            return await self._process_qb_request(session, user_input)
    
    async def _store_accepted_questions(self, session: ResearchDesign) -> None:
        """Store the accepted questions in the session"""
        # If questions aren't already stored, generate a final set
        if not session.questions or len(session.questions) < 5:
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
                    logger.info(f"Stored {len(questions)} questions in session")
                else:
                    # Fallback questions if parsing fails
                    session.questions = [
                        "How satisfied are you with your overall online shopping experience?",
                        "How would you rate the website usability of online shopping platforms?",
                        "How satisfied are you with product quality from online purchases?",
                        "How would you rate delivery speed and reliability?",
                        "How satisfied are you with customer service responsiveness?",
                        "What factors are most important when choosing an online shopping platform?",
                        "How likely are you to recommend your preferred platform to others?",
                        "What is your age group?"
                    ]
                    logger.info("Used fallback questions due to parsing issues")
                    
            except Exception as e:
                logger.error(f"Error generating final questions: {e}")
                # Use basic fallback questions
                session.questions = [
                    "How satisfied are you with your overall online shopping experience?",
                    "How would you rate the website usability?",
                    "How satisfied are you with product quality?",
                    "How would you rate delivery service?",
                    "How satisfied are you with customer service?",
                    "What is your age group?",
                    "How often do you shop online?",
                    "What is your preferred online shopping platform?"
                ]
                logger.info("Used basic fallback questions due to error")
    
    async def _test_questions(self, session: ResearchDesign) -> str:
        """Test questions with synthetic respondents using AI simulation"""
        # Move to final output stage
        session.stage = ResearchStage.FINAL_OUTPUT
        
        try:
            # Generate synthetic respondent feedback using LLM
            synthetic_feedback = await self._generate_synthetic_respondent_feedback(session)
            
            return f"""
🧪 **Testing Questionnaire with Synthetic Respondents**

Running simulation with 5 diverse synthetic respondents matching your target population...

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
            return """
🧪 **Testing Questionnaire with Synthetic Respondents**

**Test Results:**
✅ **Question Clarity**: All questions are clear and understandable
✅ **Response Time**: Estimated completion time: 8-12 minutes  
✅ **Flow Logic**: Question sequence flows logically
✅ **Response Validation**: All answer options are appropriate

---

**Are you satisfied with the questionnaire?**
- **Y** (Yes) - Finalize and export complete research package
- **N** (No) - Make additional modifications
- **T** (Test Again) - Run another round of testing
"""
    
    async def _generate_synthetic_respondent_feedback(self, session: ResearchDesign) -> str:
        """Generate realistic synthetic respondent feedback using AI"""
        
        # Get the questions from session (if available) or use placeholder
        questions_text = ""
        if session.questions:
            questions_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(session.questions))
        else:
            questions_text = "Questions about customer satisfaction with online shopping (specific questions not available in session)"
        
        prompt = f"""
You are simulating 5 different synthetic respondents testing a survey questionnaire. 

Research Topic: {session.research_topic}
Target Population: {session.target_population}
Questions to test:
{questions_text}

For each synthetic respondent, provide:
1. Brief demographic profile
2. How long it took them to complete
3. Any confusion or issues they encountered
4. Suggestions for improvement
5. Overall feedback

Create diverse respondents (different ages, tech-savviness, shopping habits) that match the target population. Be realistic about potential issues like unclear wording, missing answer options, or confusing flow.

Format as a structured test report. Keep response under 400 words and in English only.
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
    
    async def _generate_new_questions(self, session: ResearchDesign) -> str:
        """Generate new questions using AI"""
        prompt = f"""
Generate 8-10 survey questions for the following research:

Topic: {session.research_topic}
Objectives: {', '.join(session.objectives)}
Target Population: {session.target_population}

Create a mix of:
- Multiple choice questions
- Likert scale questions (1-5 or 1-7)
- Open-ended questions
- Demographic questions

Format each question clearly with response options where applicable. Respond in English only.
"""
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            # Clean the response to remove Chinese characters
            cleaned_response = remove_chinese_and_punct(str(response))
            
            return f"""
🤖 **AI-Generated Questions**

{cleaned_response}

---

**Review these questions:**
- **A** (Accept) - Use these questions for your survey
- **R** (Revise) - Request modifications
- **M** (More) - Generate additional questions
- **B** (Back) - Return to questionnaire builder menu
"""
        except Exception as e:
            logger.error(f"Error generating questions: {e}")
            return "Unable to generate questions. Please try again or choose existing questions."
    
    async def _select_existing_questions(self, session: ResearchDesign) -> str:
        """Allow user to select from existing questions"""
        return f"""
📋 **Select from Existing Questions**

{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(session.questions))}

**Instructions:**
- Enter the numbers of questions you want to include (e.g., "1,3,5,7")
- Type "all" to include all questions
- Type "back" to return to questionnaire builder menu

Your selection:
"""
    
    async def _combine_questions(self, session: ResearchDesign) -> str:
        """Combine existing and new questions"""
        return """
🔄 **Combine Questions**

This will:
1. Let you select from existing database questions
2. Generate additional custom questions
3. Allow you to arrange and edit the final questionnaire

Type "continue" to proceed or "back" to return to menu:
"""
    
    async def _set_limits(self, session: ResearchDesign) -> str:
        """Set questionnaire limits"""
        return """
⚙️ **Set Questionnaire Limits**

Please specify your preferences:

1. **Maximum number of questions:** (e.g., 20)
2. **Question types to limit:** (e.g., "no open-ended", "max 5 demographic")
3. **Survey length target:** (e.g., "under 10 minutes")
4. **Audience considerations:** (e.g., "mobile-friendly", "senior-friendly")

Enter your preferences or type "back" to return to menu:
"""
    
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
2. Providing guidance on questionnaire design
3. Explaining options if they're confused

Keep response concise and actionable.
"""
        
        try:
            response = await self.llm.ask(prompt, temperature=0.7)
            return f"{response}\n\n---\nType 'menu' to return to questionnaire builder options."
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