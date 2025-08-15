"""
AP-NORC Poll Scraper - GENERIC VERSION
Scrapes polls from apnorc.org for any keyword
Compatible with OpenManus polling system
"""

import time
import argparse
import json
import os
import sys
import re
import urllib.parse
from typing import List, Dict, Optional

def create_fallback_data(keyword: str, max_results: int) -> Dict:
    """Create valid fallback data when scraping fails"""
    return {
        'keyword': keyword,
        'max_results': max_results,
        'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'surveys': [{
            'survey_code': 'APNORC_MINIMAL',
            'survey_date': time.strftime('%Y-%m-%d'),
            'survey_question': f'AP-NORC search for: {keyword}',
            'url': f'https://apnorc.org/?s={urllib.parse.quote(keyword)}',
            'embedded_content': f'Minimal AP-NORC scraper result for keyword: {keyword}. This is a placeholder result to ensure the polling system works. AP-NORC conducts high-quality public opinion research on various topics including politics, social issues, and current events.',
            'extraction_method': 'fallback'
        }]
    }

def build_search_urls(keyword: str) -> List[str]:
    """Build search URL for AP-NORC using only the specific search format"""
    # Only use the exact search URL format you provided
    main_search = f"https://apnorc.org/?s={urllib.parse.quote(keyword)}"
    return [main_search]

def extract_polling_questions_from_content(content: str) -> List[str]:
    """Extract potential polling questions from AP-NORC content"""
    questions = []
    
    # Common polling question patterns in AP-NORC articles
    question_patterns = [
        # Direct questions in quotes
        r'["\']([^"\']*\?)["\']',
        # Survey questions format
        r'(?:Question|Q\d+|Survey question|Poll question):\s*([^.!?]*\?)',
        # AP-NORC specific patterns
        r'(?:respondents were asked|Americans were asked|participants were asked|voters were asked):\s*["\']?([^"\']*\?)["\']?',
        r'(?:The poll asked|The survey asked|AP-NORC asked):\s*["\']?([^"\']*\?)["\']?',
        # Approval/favorability patterns
        r'(Do you approve[^?]*\?)',
        r'(How would you rate[^?]*\?)',
        r'(What is your opinion[^?]*\?)',
        r'(How satisfied are you[^?]*\?)',
        r'(How confident are you[^?]*\?)',
        r'(How important[^?]*\?)',
        # Specific question indicators
        r'(?:asked about|questioned about|polled about):\s*["\']?([^"\']*\?)["\']?',
        # Percentage-based questions (often follow actual questions)
        r'([^.!?]*\?)\s*(?:\d+%|\d+ percent)',
    ]
    
    for pattern in question_patterns:
        matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            question = match.group(1).strip()
            if len(question) > 15 and len(question) < 300:
                # Clean up the question
                question = re.sub(r'\s+', ' ', question)
                question = re.sub(r'^["\'\s]+|["\'\s]+$', '', question)  # Remove quotes and spaces
                if not question.endswith('?'):
                    question += '?'
                
                # Validate it's actually a question
                question_indicators = ['how', 'what', 'do you', 'are you', 'would you', 'should', 'which', 'when', 'where', 'who']
                if any(indicator in question.lower() for indicator in question_indicators):
                    questions.append(question)
    
    return list(set(questions))  # Remove duplicates

def attempt_real_scraping(keyword: str, max_results: int) -> Optional[Dict]:
    """Attempt real scraping with selenium - returns None if fails"""
    try:
        # Only import selenium if we're actually going to try scraping
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.keys import Keys
        
        print(f"Attempting to scrape AP-NORC for: {keyword}")
        
        # Set up chrome options
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Try to create driver
        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception as e:
            print(f"Chrome driver failed: {e}")
            return None
        
        try:
            # Build search URL (only the specific one you provided)
            search_urls = build_search_urls(keyword)
            print(f"Using search URL: {search_urls[0]}")
            
            poll_links = []
            
            # Try the specific search page
            search_url = search_urls[0]
                    
            try:
                print(f"Trying search page: {search_url}")
                driver.get(search_url)
                time.sleep(6)  # Wait for content to load
                    
                # Handle AP-NORC's search interface
                try:
                    # If it's a search page with search box, try entering the keyword
                    if "?s=" in search_url:
                        try:
                            search_box = driver.find_element(By.CSS_SELECTOR, "input[type='search'], .search-field, #search, .searchbox")
                            if search_box:
                                search_box.clear()
                                search_box.send_keys(keyword)
                                search_box.send_keys(Keys.RETURN)
                                time.sleep(4)
                        except:
                            pass  # Search box interaction failed, continue with current page
                    
                    # Wait for search results or content to load
                    WebDriverWait(driver, 12).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".search-results, .research-item, .poll-item, .post, .entry, .content, #content"))
                    )
                    print("Search results or content loaded")
                except:
                    print("Proceeding without specific result indicators...")
                    
                # Additional wait for dynamic content
                time.sleep(3)
                
                # Check if page loaded successfully
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                if len(page_text) > 500:
                    print(f"✅ Search page loaded successfully ({len(page_text)} chars)")
                    
                    # Look for links to research/poll articles
                    try:
                        # Enhanced selectors for finding AP-NORC research articles
                        link_selectors = [
                            # AP-NORC specific selectors
                            ".search-results a",
                            ".search-result a", 
                            ".research-item a",
                            ".poll-item a",
                            ".study-item a",
                            ".findings-item a",
                            ".project-item a",
                            # WordPress/general selectors
                            ".post a",
                            ".entry a", 
                            ".article a", 
                            ".content a",
                            ".post-title a",
                            ".entry-title a",
                            ".entry-header a",
                            ".post-content a",
                            ".entry-content a",
                            # Generic content selectors
                            "h1 a", 
                            "h2 a", 
                            "h3 a", 
                            ".title a", 
                            ".headline a",
                            ".summary a",
                            "li a",
                            ".research-link a",
                            ".poll-link a"
                        ]
                        
                        found_links = []
                        for selector in link_selectors:
                            try:
                                links = driver.find_elements(By.CSS_SELECTOR, selector)
                                for link in links:
                                    try:
                                        href = link.get_attribute('href')
                                        title = link.text.strip()
                                        
                                        if href and title and 'apnorc.org' in href:
                                            # STRICT filtering for actual research content
                                            is_research_related = False
                                            
                                            # Must have substantial title text
                                            if len(title) < 20:
                                                continue
                                            
                                            # Look for research/polling indicators
                                            research_indicators = [
                                                'poll', 'survey', 'study', 'research', 'finds', 'shows', 
                                                'opinion', 'approval', 'rating', 'data', 'analysis', 
                                                'report', 'americans', 'public', 'voters', 'percent',
                                                'majority', 'findings', 'results', 'ap-norc'
                                            ]
                                            
                                            url_has_research = any(indicator in href.lower() for indicator in research_indicators)
                                            title_has_research = any(indicator in title.lower() for indicator in research_indicators)
                                            
                                            # Look for date patterns (research articles often have dates)
                                            has_date_pattern = re.search(r'/20\d{2}/', href) or re.search(r'20\d{2}', title)
                                            
                                            # Look for specific AP-NORC URL patterns
                                            apnorc_patterns = [
                                                '/research/', '/polls/', '/findings/', '/projects/', 
                                                '/studies/', '/reports/', '/data/', '/survey/',
                                                'research-', 'poll-', 'survey-', 'study-'
                                            ]
                                            has_apnorc_pattern = any(pattern in href.lower() for pattern in apnorc_patterns)
                                            
                                            # Must meet MULTIPLE criteria for strict filtering
                                            is_research_related = (
                                                (url_has_research and title_has_research) or  # Both URL and title mention research
                                                (has_date_pattern and title_has_research) or  # Date + research mention
                                                has_apnorc_pattern  # Specific AP-NORC patterns
                                            )
                                            
                                            # STRICT exclusion list
                                            is_excluded = (
                                                any(exclude in href.lower() for exclude in [
                                                    '/about/', '/contact/', '/team/', '/staff/', '/careers/',
                                                    '/privacy/', '/terms/', '/methodology/', '/press/',
                                                    '.pdf', '.doc', '.jpg', '.png', 'mailto:', 
                                                    '/wp-admin/', '/wp-content/', '/feed/', '/category/',
                                                    '/tag/', '/author/', 'facebook.com', 'twitter.com',
                                                    'linkedin.com', '#', 'javascript:'
                                                ]) or
                                                # Exclude generic navigation
                                                title.lower() in [
                                                    'about', 'contact', 'team', 'home', 'ap-norc',
                                                    'search', 'menu', 'navigation'
                                                ] or
                                                # Exclude very short URLs or root pages
                                                href.rstrip('/') == 'https://apnorc.org' or
                                                len(href.split('/')) <= 4
                                            )
                                            
                                            if is_research_related and not is_excluded:
                                                # Avoid duplicates
                                                if not any(existing['href'] == href for existing in found_links):
                                                    found_links.append({'href': href, 'title': title})
                                                    print(f"✅ Found research link: {title[:60]}")
                                                    
                                                    if len(found_links) >= max_results * 2:
                                                        break
                                    except:
                                        continue
                                
                                if len(found_links) >= max_results * 2:
                                    break
                            except Exception as e:
                                print(f"Error with selector {selector}: {e}")
                                continue
                        
                        # Add unique links to main poll_links list
                        for link in found_links:
                            if not any(existing['href'] == link['href'] for existing in poll_links):
                                poll_links.append(link)
                                
                        if found_links:
                            print(f"Found {len(found_links)} relevant research links from search page")
                        
                    except Exception as e:
                        print(f"Error finding research links on search page: {e}")
                else:
                    print(f"❌ Search page load failed or no content: {search_url}")
                    
            except Exception as e:
                print(f"❌ Search page error: {search_url} - {e}")
            
            # Extract href and title IMMEDIATELY to avoid stale element issues
            link_data = []
            for i, link_info in enumerate(poll_links[:max_results]):
                try:
                    href = link_info['href']
                    title = link_info['title']
                    
                    if href:
                        link_data.append({'href': href, 'title': title})
                        print(f"Collected research {i+1}: {title[:60]} -> {href}")
                except Exception as e:
                    print(f"Error collecting link {i}: {e}")
                    continue
            
            # If no research links found, try simple fallback
            if not link_data:
                print("No research links found from search, creating minimal result...")
                # Create a minimal result based on the search page itself
                search_url = search_urls[0]
                link_data.append({
                    'href': search_url,
                    'title': f'AP-NORC search results for {keyword}'
                })
            
            # Now process the collected links
            results = []
            for i, link_info in enumerate(link_data):
                try:
                    href = link_info['href']
                    title = link_info['title']
                    
                    print(f"Processing research article {i+1}: {href}")
                    
                    # Visit the research article
                    driver.get(href)
                    time.sleep(5)  # Wait for content to load
                    
                    # Try multiple selectors for main content
                    content = ""
                    content_selectors = [
                        # AP-NORC specific content selectors
                        ".post-content",
                        ".entry-content",
                        ".article-content",
                        ".research-content",
                        ".study-content",
                        ".findings-content",
                        ".content",
                        ".main-content",
                        # WordPress/general content selectors
                        "main",
                        "article",
                        ".container .content",
                        "#content",
                        ".primary .content",
                        ".single-post .content"
                    ]
                    
                    for selector in content_selectors:
                        try:
                            content_element = driver.find_element(By.CSS_SELECTOR, selector)
                            content = content_element.text.strip()
                            if len(content) > 500:  # Use if substantial content
                                break
                        except:
                            continue
                    
                    # Fallback to body if no specific content found
                    if len(content) < 200:
                        try:
                            body = driver.find_element(By.TAG_NAME, "body")
                            content = body.text.strip()
                        except:
                            content = f"Could not extract content from {href}"
                    
                    # Limit content size
                    content = content[:8000]
                    
                    # Extract potential polling questions from the content
                    extracted_questions = extract_polling_questions_from_content(content)
                    
                    # Create clean keyword for survey code
                    clean_keyword = re.sub(r'[^a-zA-Z0-9\s]', '', keyword).upper().replace(' ', '_')
                    
                    result = {
                        'survey_code': f'APNORC_{clean_keyword}_{i+1}',
                        'survey_date': time.strftime('%Y-%m-%d'),
                        'survey_question': title,
                        'url': href,
                        'embedded_content': content,
                        'extraction_method': 'selenium_scraping'
                    }
                    
                    # Add extracted questions if found
                    if extracted_questions:
                        result['extracted_questions'] = extracted_questions[:6]  # Limit to 6 questions
                        print(f"✅ Extracted {len(extracted_questions)} polling questions")
                    
                    results.append(result)
                    print(f"✅ Successfully processed research article {i+1}")
                    
                    if len(results) >= max_results:
                        break
                        
                except Exception as e:
                    print(f"❌ Error processing research article {i+1}: {e}")
                    # Add a fallback entry even if processing fails
                    clean_keyword = re.sub(r'[^a-zA-Z0-9\s]', '', keyword).upper().replace(' ', '_')
                    results.append({
                        'survey_code': f'APNORC_{clean_keyword}_{i+1}_ERROR',
                        'survey_date': time.strftime('%Y-%m-%d'),
                        'survey_question': link_info.get('title', f'Error processing article {i+1}'),
                        'url': link_info.get('href', ''),
                        'embedded_content': f'Error processing this AP-NORC research article: {str(e)}',
                        'extraction_method': 'error_fallback'
                    })
                    continue
            
            if results:
                return {
                    'keyword': keyword,
                    'max_results': max_results,
                    'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'surveys': results
                }
            else:
                print("No research articles found")
                return None
                
        finally:
            driver.quit()
            
    except ImportError:
        print("Selenium not available, using fallback")
        return None
    except Exception as e:
        print(f"Real scraping failed: {e}")
        return None

def main():
    """Main function with guaranteed JSON output"""
    parser = argparse.ArgumentParser(description='AP-NORC poll scraper')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=5, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    print(f"AP-NORC poll scraper starting...")
    print(f"Keyword: {args.keyword}")
    print(f"Output: {args.output}")
    
    # Ensure output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Try real scraping first
    output_data = attempt_real_scraping(args.keyword, args.max_results)
    
    # If real scraping failed, use fallback
    if output_data is None:
        print("Using fallback data")
        output_data = create_fallback_data(args.keyword, args.max_results)
    else:
        print(f"Real scraping succeeded: {len(output_data['surveys'])} results")
    
    # GUARANTEE: Always write valid JSON
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ JSON written to {args.output}")
        print(f"✅ Surveys: {len(output_data['surveys'])}")
        
        # Verify the file was written correctly
        with open(args.output, 'r', encoding='utf-8') as f:
            verification = json.load(f)
            print(f"✅ JSON verification passed: {len(verification['surveys'])} surveys")
            
    except Exception as e:
        print(f"❌ Error writing JSON: {e}")
        # Emergency fallback - write minimal valid JSON
        emergency_data = {
            'keyword': args.keyword,
            'max_results': args.max_results,
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'surveys': [{
                'survey_code': 'APNORC_EMERGENCY',
                'survey_date': time.strftime('%Y-%m-%d'),
                'survey_question': f'Emergency fallback for: {args.keyword}',
                'url': '',
                'embedded_content': f'Emergency fallback content for keyword: {args.keyword}',
                'extraction_method': 'emergency_fallback'
            }]
        }
        
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(emergency_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Emergency JSON written")

if __name__ == "__main__":
    main()