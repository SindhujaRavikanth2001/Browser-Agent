from pydantic import Field  
from app.agent.browser import BrowserAgent
from app.config import config
from app.prompt.browser import NEXT_STEP_PROMPT as BROWSER_NEXT_STEP_PROMPT
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.tool import Terminate, ToolCollection
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.python_execute import PythonExecute
from app.tool.str_replace_editor import StrReplaceEditor
from app.llm import LLM


class Manus(BrowserAgent):
    """
    A versatile general-purpose agent that uses planning to solve various tasks.

    This agent extends BrowserAgent with a comprehensive set of tools and capabilities,
    including Python execution, web browsing, file operations, and information retrieval
    to handle a wide range of user requests.
    """

    name: str = "Manus"
    description: str = (
        "A versatile agent that can solve various tasks using multiple tools"
    )

    # Enhanced system prompt with better task completion logic
    system_prompt: str = f"""
You are a helpful assistant.  
- Always respond in English only (no other languages).  
- When citing, use “Source:” not “来源:”.  
{SYSTEM_PROMPT.format(directory=config.workspace_root)}

CRITICAL TASK COMPLETION INSTRUCTIONS:
- You must FULLY COMPLETE the user's request before terminating
- You must give the full reponse in English. Don't include any other language.
- For multi-part requests (like "extract content AND generate something"), complete BOTH parts
- Only use 'terminate' after you have completely addressed all aspects of the user's request
- If you've extracted content but haven't used it to complete the requested task, CONTINUE WORKING
- Avoid redundant content extractions - if you already have the content, use it directly
- Focus on efficiency: extract once, then use that content to complete the full task

CONTENT EXTRACTION EFFICIENCY:
- If you've already extracted content from a webpage, don't extract it again
- Use the extracted content to directly complete the user's goal
- Combine content extraction with goal completion in a single step when possible
"""

    next_step_prompt: str = NEXT_STEP_PROMPT

    max_observe: int = 15000  # Increased for better content handling
    max_steps: int = 8  # Reduced back to 8 since we're being more efficient

    # Initialize LLM
    llm: LLM

    # Track task completion state
    task_state: dict = Field(default_factory=dict, exclude=True)

    def __init__(self, **data):
        super().__init__(**data)
        # Initialize tools with LLM instance
        self.available_tools = ToolCollection(
            PythonExecute(), 
            BrowserUseTool(llm=self.llm),
            StrReplaceEditor(), 
            Terminate()
        )

    async def think(self) -> bool:
        """Enhanced thinking process with better task completion logic."""
        
        # Analyze the current conversation state
        if self.memory.messages:
            user_messages = [msg for msg in self.memory.messages if msg.role == "user"]
            assistant_messages = [msg for msg in self.memory.messages if msg.role == "assistant"]
            
            if user_messages:
                original_request = user_messages[0].content.lower()
                
                # Detect multi-part requests
                multi_part_indicators = [
                    "and generate", "then create", "and create", "then generate", 
                    "and make", "then make", "and produce", "then produce",
                    "and build", "then build", "and write", "then write",
                    "survey questions", "create questions", "make questions"
                ]
                
                is_multi_part = any(indicator in original_request for indicator in multi_part_indicators)
                
                if is_multi_part:
                    # Check completion status
                    recent_content = " ".join([msg.content for msg in assistant_messages[-3:] if hasattr(msg, 'content')])
                    
                    has_extracted = any(phrase in recent_content.lower() for phrase in [
                        "extracted", "content extraction", "beautifulsoup", "structured content"
                    ])
                    
                    has_completed_goal = any(phrase in recent_content.lower() for phrase in [
                        "survey questions", "questions:", "1.", "2.", "3.", "questionnaire",
                        "based on the content", "here are", "complete response"
                    ])
                    
                    # Update task state
                    self.task_state.update({
                        'is_multi_part': is_multi_part,
                        'has_extracted': has_extracted,
                        'has_completed_goal': has_completed_goal,
                        'original_request': original_request
                    })
                    
                    # If we've extracted but not completed the goal, emphasize completion
                    if has_extracted and not has_completed_goal:
                        self.next_step_prompt = f"""
{NEXT_STEP_PROMPT}

URGENT TASK COMPLETION REQUIRED:
You have successfully extracted content from the webpage, but you have NOT yet completed the user's full request.

The user asked you to: {original_request}

You've completed the extraction part, but you must now use that extracted information to complete the second part of the task.

IMPORTANT: 
- Do NOT extract content again - you already have it
- Use the content you've already extracted to directly complete the user's goal
- Generate the complete response based on the extracted content
- Only terminate after you've fully addressed the user's request

Continue with completing the task now.
"""
                    elif has_extracted and has_completed_goal:
                        # Task appears complete, but let's make sure
                        self.next_step_prompt = f"""
{NEXT_STEP_PROMPT}

TASK COMPLETION CHECK:
You appear to have both extracted content and completed the user's goal. 

Before terminating, verify that:
1. You have extracted the required content from the webpage
2. You have used that content to fully address the user's specific request
3. Your response is complete and actionable

If all parts are complete, you may terminate. If anything is missing or incomplete, complete it now.
"""

        # Store original prompt for restoration
        original_prompt = self.next_step_prompt

        # Check for browser activity to determine context
        recent_messages = self.memory.messages[-3:] if self.memory.messages else []
        browser_in_use = any(
            "browser_use" in str(msg.content).lower()
            for msg in recent_messages
            if hasattr(msg, "content")
        )

        if browser_in_use:
            # Use browser-specific prompt temporarily
            self.next_step_prompt = BROWSER_NEXT_STEP_PROMPT

        # Call parent's think method
        result = await super().think()

        # Restore original prompt
        self.next_step_prompt = original_prompt

        return result

    async def plan_and_execute_task(self, task: str) -> str:
        """Enhanced task planning and execution with better completion tracking."""
        
        # Analyze task complexity
        task_lower = task.lower()
        
        # Detect if this is a content extraction + generation task
        is_extract_and_generate = any(pattern in task_lower for pattern in [
            "extract" and "generate", "go to" and "create", "visit" and "make"
        ])
        
        if is_extract_and_generate:
            # Plan for efficient execution
            execution_plan = [
                "1. Navigate to the specified webpage",
                "2. Extract comprehensive content using BeautifulSoup",
                "3. Use the extracted content to complete the specific goal (e.g., generate survey questions)",
                "4. Provide complete, actionable results",
                "5. Terminate only after full completion"
            ]
            
            # Store the plan for reference
            self.task_state['execution_plan'] = execution_plan
            self.task_state['current_step'] = 1
        
        # Execute the task using the parent method
        return await super().run(task, max_steps=self.max_steps)

    def should_terminate(self) -> bool:
        """Enhanced termination logic to prevent premature termination."""
        
        # Check if we have a multi-part task
        if self.task_state.get('is_multi_part', False):
            has_extracted = self.task_state.get('has_extracted', False)
            has_completed_goal = self.task_state.get('has_completed_goal', False)
            
            # Only terminate if both parts are complete
            if has_extracted and has_completed_goal:
                return True
            else:
                return False
        
        # For single-part tasks, use default logic
        return super().should_terminate() if hasattr(super(), 'should_terminate') else False