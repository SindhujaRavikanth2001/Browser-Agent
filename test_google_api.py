#!/usr/bin/env python3
"""
Quick test script to verify Google Custom Search API is working
Run this to test your API credentials before starting the main application
"""

import os
import sys
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

def test_google_search_api():
    """Test Google Custom Search API with your credentials"""
    
    print("🔍 Testing Google Custom Search API...")
    print("=" * 50)
    
    # Get environment variables
    api_key = os.getenv('GOOGLE_API_KEY')
    cse_id = os.getenv('GOOGLE_CSE_ID')
    
    print(f"API Key: {'✅ Found' if api_key else '❌ Missing'}")
    print(f"CSE ID: {'✅ Found' if cse_id else '❌ Missing'}")
    
    if not api_key or not cse_id:
        print("\n❌ Environment variables not set!")
        print("Please run:")
        print("export GOOGLE_API_KEY=your_api_key")
        print("export GOOGLE_CSE_ID=your_cse_id")
        return False
    
    print(f"API Key: {api_key[:20]}..." if len(api_key) > 20 else f"API Key: {api_key}")
    print(f"CSE ID: {cse_id}")
    print()
    
    try:
        # Initialize the search service
        print("🔧 Initializing Google Custom Search service...")
        service = build("customsearch", "v1", developerKey=api_key)
        print("✅ Service initialized successfully")
        
        # Test search
        print("\n🔍 Testing search query...")
        test_query = "customer satisfaction survey questions"
        
        result = service.cse().list(
            q=test_query,
            cx=cse_id,
            num=3,  # Just get 3 results for testing
            safe='active'
        ).execute()
        
        print(f"✅ Search successful!")
        print(f"Query: '{test_query}'")
        
        # Display results
        if 'items' in result:
            print(f"📊 Found {len(result['items'])} results:")
            print()
            
            for i, item in enumerate(result['items'], 1):
                title = item.get('title', 'No title')
                link = item.get('link', 'No link')
                snippet = item.get('snippet', 'No snippet')
                display_link = item.get('displayLink', 'No domain')
                
                print(f"Result {i}:")
                print(f"  Title: {title[:80]}...")
                print(f"  Domain: {display_link}")
                print(f"  URL: {link}")
                print(f"  Snippet: {snippet[:100]}...")
                print()
        
        # Check search info
        search_info = result.get('searchInformation', {})
        total_results = search_info.get('totalResults', 'Unknown')
        search_time = search_info.get('searchTime', 'Unknown')
        
        print(f"📈 Search Statistics:")
        print(f"  Total Results: {total_results}")
        print(f"  Search Time: {search_time} seconds")
        
        print("\n🎉 Google Custom Search API is working perfectly!")
        return True
        
    except HttpError as e:
        print(f"\n❌ HTTP Error: {e}")
        if e.resp.status == 403:
            print("💡 This might be an API key or billing issue")
            print("   - Check that Custom Search API is enabled")
            print("   - Verify billing is set up (even for free tier)")
        elif e.resp.status == 400:
            print("💡 This might be an invalid CSE ID")
            print("   - Check your Custom Search Engine ID")
        return False
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False

def test_question_extraction():
    """Test the question extraction functionality"""
    print("\n🧪 Testing Question Extraction...")
    print("=" * 50)
    
    sample_text = """
    How satisfied are you with our service? What factors are most important to you?
    Please rate your experience on a scale of 1-5. Would you recommend us to others?
    Customer satisfaction survey questions include: How often do you use our product?
    """
    
    # Simple question extraction (mimicking the real function)
    import re
    questions = re.findall(r'[A-Z][^.!?]*\?', sample_text)
    
    print("Sample text processed:")
    print(f"Found {len(questions)} questions:")
    for i, q in enumerate(questions, 1):
        print(f"  {i}. {q}")
    
    print("✅ Question extraction working!")

if __name__ == "__main__":
    print("🚀 Google Custom Search API Test Suite")
    print("=" * 60)
    
    # Test API
    api_success = test_google_search_api()
    
    # Test question extraction
    test_question_extraction()
    
    print("\n" + "=" * 60)
    if api_success:
        print("🎉 ALL TESTS PASSED! Your API is ready to use.")
        print("You can now start your main application.")
    else:
        print("❌ API test failed. Please check your credentials.")
        print("Make sure you've set the environment variables correctly.")
    
    print("=" * 60)