#!/usr/bin/env python3
"""
Test script for complete content extraction and survey question generation.
This script tests the improved browser_use_tool functionality.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add the app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.agent.manus import Manus
from app.config import Config
from app.llm import LLM
from app.tool import ToolCollection
from app.tool.bash import Bash
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.create_chat_completion import CreateChatCompletion
from app.tool.planning import PlanningTool
from app.tool.str_replace_editor import StrReplaceEditor
from app.tool.terminate import Terminate


async def test_complete_extraction():
    """Test the complete content extraction and survey generation."""
    
    print("🚀 Starting Complete Content Extraction Test")
    print("=" * 60)
    
    try:
        # Initialize configuration
        config_instance = Config()
        config = config_instance._config
        
        # Create LLM instance
        llm_instance = LLM(
            model_name="Qwen/Qwen2.5-72B-Instruct",
            api_type="huggingface"
        )
        
        # Create tools
        bash_tool = Bash(config=config)
        browser_use_tool = BrowserUseTool(llm=llm_instance)
        create_chat_completion_tool = CreateChatCompletion()
        planning_tool = PlanningTool()
        str_replace_editor_tool = StrReplaceEditor()
        terminate_tool = Terminate()
        
        # Create tool collection
        manus_tools = ToolCollection(
            bash_tool,
            browser_use_tool,
            create_chat_completion_tool,
            planning_tool,
            str_replace_editor_tool,
            terminate_tool
        )
        
        # Create Manus agent
        agent = Manus(config=config, tools=manus_tools, llm=llm_instance)
        
        # Test message - the same one that was causing issues
        test_message = (
            "Go to https://bidenwhitehouse.archives.gov/briefing-room/presidential-actions/2024/09/26/"
            "executive-order-on-combating-emerging-firearms-threats-and-improving-school-based-active-shooter-drills/ "
            "and generate survey questions to gauge public opinion on gun violence in schools."
        )
        
        print(f"📝 Test Query: {test_message}")
        print("\n⏳ Starting agent execution...")
        print("=" * 60)
        
        # Start timing
        start_time = datetime.now()
        
        # Execute the task with timeout
        try:
            response = await asyncio.wait_for(
                agent.run(test_message, max_steps=8),
                timeout=600  # 10 minutes timeout
            )
            
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            
            print(f"\n✅ Task completed successfully in {execution_time:.2f} seconds!")
            print("=" * 60)
            print("📋 AGENT RESPONSE:")
            print("=" * 60)
            print(response)
            print("=" * 60)
            
            # Save the response
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"test_results/complete_extraction_test_{timestamp}.txt"
            
            # Create directory if it doesn't exist
            os.makedirs("test_results", exist_ok=True)
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"Complete Content Extraction Test Results\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Execution Time: {execution_time:.2f} seconds\n")
                f.write(f"Query: {test_message}\n")
                f.write("=" * 80 + "\n\n")
                f.write("AGENT RESPONSE:\n")
                f.write(response)
                f.write("\n\n" + "=" * 80 + "\n")
                
                # Add agent memory for debugging
                if hasattr(agent, 'memory') and agent.memory.messages:
                    f.write("CONVERSATION HISTORY:\n")
                    f.write("=" * 80 + "\n\n")
                    for i, msg in enumerate(agent.memory.messages):
                        if hasattr(msg, 'role') and hasattr(msg, 'content'):
                            f.write(f"MESSAGE {i+1} ({msg.role.upper()}):\n")
                            f.write(str(msg.content))
                            f.write("\n" + "-" * 40 + "\n\n")
            
            print(f"💾 Results saved to: {filename}")
            
            # Analyze the response
            print("\n🔍 RESPONSE ANALYSIS:")
            print("=" * 60)
            
            response_lower = response.lower()
            
            # Check for extraction indicators
            has_extraction = any(keyword in response_lower for keyword in [
                'extracted', 'beautifulsoup', 'structured content', 'content extraction'
            ])
            
            # Check for survey questions
            has_survey_questions = any(keyword in response_lower for keyword in [
                'survey questions', 'questions:', 'questionnaire', '1.', '2.', '3.'
            ]) and 'survey' in response_lower
            
            # Check for complete questions (look for question 10 or questions with multiple choice)
            has_complete_questions = ('10.' in response or '10 .' in response or 
                                    response.count('?') >= 8)  # At least 8 questions
            
            print(f"✓ Content Extraction: {'✅ YES' if has_extraction else '❌ NO'}")
            print(f"✓ Survey Questions Generated: {'✅ YES' if has_survey_questions else '❌ NO'}")
            print(f"✓ Complete Question Set: {'✅ YES' if has_complete_questions else '❌ NO'}")
            
            # Count questions
            question_count = response.count('?')
            print(f"✓ Total Questions Found: {question_count}")
            
            if has_extraction and has_survey_questions and has_complete_questions:
                print("\n🎉 TEST PASSED: Complete extraction and survey generation successful!")
                return True
            else:
                print("\n⚠️  TEST PARTIALLY SUCCESSFUL: Some components may be missing")
                return False
                
        except asyncio.TimeoutError:
            print("\n⏰ Test timed out after 10 minutes")
            
            # Try to get partial results
            if hasattr(agent, 'memory') and agent.memory.messages:
                print("📋 PARTIAL RESULTS FROM AGENT MEMORY:")
                print("=" * 60)
                
                for msg in agent.memory.messages[-3:]:  # Last 3 messages
                    if hasattr(msg, 'content') and msg.content:
                        print(str(msg.content)[:1000] + ('...' if len(str(msg.content)) > 1000 else ''))
                        print("-" * 40)
            
            return False
            
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Cleanup
        if 'agent' in locals():
            try:
                # Clean up browser resources if available
                for tool in agent.available_tools.tools:
                    if hasattr(tool, 'cleanup'):
                        await tool.cleanup()
            except:
                pass


async def main():
    """Main test function."""
    print("🧪 Complete Content Extraction Test Suite")
    print("=" * 60)
    
    success = await test_complete_extraction()
    
    if success:
        print("\n🎊 ALL TESTS PASSED!")
        exit(0)
    else:
        print("\n💔 SOME TESTS FAILED")
        exit(1)


if __name__ == "__main__":
    # Run the test
    asyncio.run(main())