"""
Ballotpedia Poll Scraper - GENERIC VERSION
Scrapes polls from ballotpedia.org for any keyword
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
            'survey_code': 'BALLOTPEDIA_MINIMAL',
            'survey_date': time.strftime('%Y-%m-%d'),
            'survey_question': f'Ballotpedia search for: {keyword}',
            'url': f'https://ballotpedia.org/wiki/index.php?search={urllib.parse.quote(keyword)}',
            'embedded_content': f'Minimal Ballotpedia scraper result for keyword: {keyword}. This is a placeholder result to ensure the polling system works. Ballotpedia contains comprehensive polling data and election information that may require more sophisticated scraping techniques.',
            'extraction_method': 'fallback'
        }]
    }

def build_search_urls(keyword: str) -> List[str]:
    """Build search URLs for Ballotpedia with different search strategies"""
  
    # Main search URL
    main_search = f"https://ballotpedia.org/wiki/index.php?search={urllib.parse.quote(keyword)}"
    return [main_search]   

def extract_polling_questions_from_content(content: str) -> List[str]:
    """Extract potential polling questions from Ballotpedia content"""
    questions = []
    
    # Common polling question patterns in Ballotpedia articles
    question_patterns = [
        # Direct questions
        r'["\']([^"\']*\?)["\']',
        # Survey questions format
        r'(?:Question|Q\d+|Poll question):\s*([^.!?]*\?)',
        # Approval/favorability patterns
        r'(Do you approve[^?]*\?)',
        r'(How would you rate[^?]*\?)',
        r'(Would you vote for[^?]*\?)',
        r'(What is your opinion[^?]*\?)',
        # Ballotpedia specific patterns
        r'(?:respondents were asked|voters were asked|participants were asked):\s*["\']?([^"\']*\?)["\']?',
    ]
    
    for pattern in question_patterns:
        matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            question = match.group(1).strip()
            if len(question) > 20 and len(question) < 300:
                # Clean up the question
                question = re.sub(r'\s+', ' ', question)
                if not question.endswith('?'):
                    question += '?'
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
        
        print(f"Attempting to scrape Ballotpedia for: {keyword}")
        
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
            # Build search URLs
            search_urls = build_search_urls(keyword)
            print(f"Will try {len(search_urls)} search pages")
            
            poll_links = []
            
            # Try each search page
            for search_url in search_urls:
                if len(poll_links) >= max_results * 2:
                    break
                    
                try:
                    print(f"Trying search page: {search_url}")
                    driver.get(search_url)
                    time.sleep(5)  # Wait for content to load
                    
                    # Handle Ballotpedia's search interface
                    try:
                        # If it's a search page with search box, try entering the keyword
                        if "index.php?search=" in search_url or "Special:Search" in search_url:
                            try:
                                search_box = driver.find_element(By.CSS_SELECTOR, "#searchInput, .searchText, input[name='search']")
                                if search_box:
                                    search_box.clear()
                                    search_box.send_keys(keyword)
                                    search_box.send_keys(Keys.RETURN)
                                    time.sleep(3)
                            except:
                                pass  # Search box interaction failed, continue with current page
                        
                        # Wait for search results or content to load
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".searchresults, .mw-search-results, .mw-content-text, #content"))
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
                        
                        # Look for links to polling/research articles
                        try:
                            # Enhanced selectors for finding polling articles
                            link_selectors = [
                                # Ballotpedia specific selectors
                                ".searchresults a",
                                ".mw-search-results a", 
                                ".mw-search-result-heading a",
                                ".search-result-heading a",
                                # MediaWiki content selectors
                                ".mw-content-text a",
                                "#mw-content-text a",
                                "#content a",
                                ".mw-parser-output a",
                                # General content selectors
                                "h1 a", 
                                "h2 a", 
                                "h3 a", 
                                ".title a", 
                                ".headline a",
                                "li a",
                                "p a"
                            ]
                            
                            found_links = []
                            for selector in link_selectors:
                                try:
                                    links = driver.find_elements(By.CSS_SELECTOR, selector)
                                    for link in links:
                                        try:
                                            href = link.get_attribute('href')
                                            title = link.text.strip()
                                            
                                            if href and title and 'ballotpedia.org' in href:
                                                # STRICT filtering for actual polling content
                                                is_polling_related = False
                                                
                                                # Must have substantial title text
                                                if len(title) < 15:
                                                    continue
                                                
                                                # Look for polling/election indicators
                                                polling_indicators = [
                                                    'poll', 'polling', 'survey', 'approval', 'rating', 'opinion',
                                                    'election', 'candidate', 'primary', 'general', 'ballot',
                                                    'vote', 'voter', 'campaign', 'race', 'contest', 'results',
                                                    'data', 'statistics', 'percentage', 'margin', 'lead'
                                                ]
                                                
                                                url_has_polling = any(indicator in href.lower() for indicator in polling_indicators)
                                                title_has_polling = any(indicator in title.lower() for indicator in polling_indicators)
                                                
                                                # Look for year patterns (election/polling data often has years)
                                                has_year_pattern = re.search(r'20\d{2}', href) or re.search(r'20\d{2}', title)
                                                
                                                # Look for specific Ballotpedia URL patterns
                                                ballotpedia_patterns = [
                                                    '/polls', '/polling', '/election', '/primary', '/general',
                                                    '_election', '_primary', '_polls', '_polling', '_approval'
                                                ]
                                                has_ballotpedia_pattern = any(pattern in href.lower() for pattern in ballotpedia_patterns)
                                                
                                                # Must meet criteria for polling content
                                                is_polling_related = (
                                                    (url_has_polling or title_has_polling) or
                                                    has_ballotpedia_pattern or
                                                    (has_year_pattern and (url_has_polling or title_has_polling))
                                                )
                                                
                                                # STRICT exclusion list
                                                is_excluded = (
                                                    any(exclude in href.lower() for exclude in [
                                                        '/talk:', '/user:', '/special:', '/help:', '/template:',
                                                        '/category:', '/file:', '/image:', '#', 'action=edit',
                                                        'ballotpedia.org/Main_Page', 'ballotpedia.org/Ballotpedia',
                                                        'facebook.com', 'twitter.com', 'mailto:', '.pdf', '.doc'
                                                    ]) or
                                                    # Exclude navigation and generic pages
                                                    title.lower() in [
                                                        'ballotpedia', 'main page', 'home', 'about', 'contact',
                                                        'help', 'search', 'special pages'
                                                    ] or
                                                    # Exclude very short titles
                                                    len(title) < 15
                                                )
                                                
                                                if is_polling_related and not is_excluded:
                                                    # Avoid duplicates
                                                    if not any(existing['href'] == href for existing in found_links):
                                                        found_links.append({'href': href, 'title': title})
                                                        print(f"✅ Found polling link: {title[:60]}")
                                                        
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
                                print(f"Found {len(found_links)} relevant polling links from this search page")
                            
                        except Exception as e:
                            print(f"Error finding polling links on search page: {e}")
                    else:
                        print(f"❌ Search page load failed or no content: {search_url}")
                        
                except Exception as e:
                    print(f"❌ Search page error: {search_url} - {e}")
                    continue
            
            # Extract href and title IMMEDIATELY to avoid stale element issues
            link_data = []
            for i, link_info in enumerate(poll_links[:max_results]):
                try:
                    href = link_info['href']
                    title = link_info['title']
                    
                    if href:
                        link_data.append({'href': href, 'title': title})
                        print(f"Collected polling article {i+1}: {title[:60]} -> {href}")
                except Exception as e:
                    print(f"Error collecting link {i}: {e}")
                    continue
            
            # If no polling links found, try fallback search
            if not link_data:
                print("No polling links found, trying fallback search...")
                try:
                    # Go to main Ballotpedia page and search
                    driver.get("https://ballotpedia.org")
                    time.sleep(3)
                    
                    # Try to use the search box on main page
                    try:
                        search_box = driver.find_element(By.CSS_SELECTOR, "#searchInput, .searchText")
                        search_box.clear()
                        search_box.send_keys(f"{keyword} polling")
                        search_box.send_keys(Keys.RETURN)
                        time.sleep(5)
                        
                        # Look for any relevant links
                        fallback_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='ballotpedia.org']")
                        for link in fallback_links[:max_results]:
                            try:
                                href = link.get_attribute('href')
                                title = link.text.strip()
                                if href and title and len(title) > 20:
                                    link_data.append({'href': href, 'title': title})
                                    print(f"Fallback link: {title[:50]}")
                            except:
                                continue
                                
                    except Exception as e:
                        print(f"Fallback search failed: {e}")
                    
                except Exception as debug_e:
                    print(f"Fallback failed: {debug_e}")
            
            # Now process the collected links
            results = []
            for i, link_info in enumerate(link_data):
                try:
                    href = link_info['href']
                    title = link_info['title']
                    
                    print(f"Processing polling article {i+1}: {href}")
                    
                    # Visit the polling article
                    driver.get(href)
                    time.sleep(4)  # Wait for content to load
                    
                    # Try multiple selectors for main content
                    content = ""
                    content_selectors = [
                        # MediaWiki/Ballotpedia specific content selectors
                        ".mw-content-text",
                        "#mw-content-text", 
                        ".mw-parser-output",
                        "#content",
                        ".content",
                        "main",
                        "article",
                        "#bodyContent"
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
                        'survey_code': f'BALLOTPEDIA_{clean_keyword}_{i+1}',
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
                    print(f"✅ Successfully processed polling article {i+1}")
                    
                    if len(results) >= max_results:
                        break
                        
                except Exception as e:
                    print(f"❌ Error processing polling article {i+1}: {e}")
                    # Add a fallback entry even if processing fails
                    clean_keyword = re.sub(r'[^a-zA-Z0-9\s]', '', keyword).upper().replace(' ', '_')
                    results.append({
                        'survey_code': f'BALLOTPEDIA_{clean_keyword}_{i+1}_ERROR',
                        'survey_date': time.strftime('%Y-%m-%d'),
                        'survey_question': link_info.get('title', f'Error processing article {i+1}'),
                        'url': link_info.get('href', ''),
                        'embedded_content': f'Error processing this Ballotpedia article: {str(e)}',
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
                print("No polling articles found")
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
    parser = argparse.ArgumentParser(description='Ballotpedia poll scraper')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=5, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    print(f"Ballotpedia poll scraper starting...")
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
                'survey_code': 'BALLOTPEDIA_EMERGENCY',
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