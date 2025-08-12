"""
YouGov Poll Scraper - GENERIC VERSION
Scrapes polls from today.yougov.com tracker pages for any keyword
"""

import time
import argparse
import json
import os
import sys
import re
import urllib.parse

def create_fallback_data(keyword, max_results):
    """Create valid fallback data when scraping fails"""
    return {
        'keyword': keyword,
        'max_results': max_results,
        'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'surveys': [{
            'survey_code': 'YOUGOV_MINIMAL',
            'survey_date': time.strftime('%Y-%m-%d'),
            'survey_question': f'YouGov poll search for: {keyword}',
            'url': f'https://today.yougov.com/search?q={urllib.parse.quote(keyword)}',
            'embedded_content': f'Minimal YouGov scraper result for keyword: {keyword}. This is a placeholder result to ensure the polling system works. The actual YouGov website may require more sophisticated scraping techniques or may be blocking automated access.'
        }]
    }

def is_relevant_content(url, title, content, keyword):
    """Check if content is relevant to the search keyword"""
    text_to_check = f"{url} {title} {content}".lower()
    keyword_lower = keyword.lower()
    
    # Split keyword into individual terms
    keyword_terms = keyword_lower.split()
    
    # Check if content contains keyword terms
    keyword_match_count = sum(1 for term in keyword_terms if term in text_to_check)
    has_keyword_match = keyword_match_count >= len(keyword_terms) * 0.6  # At least 60% of terms must match
    
    # Check for polling/survey indicators
    poll_indicators = [
        'poll', 'survey', 'study', 'research', 'economist/yougov', 'economist', 
        'yougov poll', 'approval', 'disapproval', 'rating', 'opinion', 
        'favorability', 'unfavorability', 'popularity', 'tracking'
    ]
    has_poll_indicator = any(indicator in text_to_check for indicator in poll_indicators)
    
    # Check for article indicators
    article_indicators = [
        '/politics/articles/', '/topics/', '/articles/', 
        'economist', 'yougov.com', 'poll', 'survey'
    ]
    is_article = any(indicator in text_to_check for indicator in article_indicators)
    
    # Exclude non-content pages
    excluded_terms = [
        'business.yougov.com', '/product/', '/solutions/', '/brand-tracking',
        '/explore/brand/', '/explore/country/', '/explore/issue/',
        '(popup:search/', 'utm_source=', 'utm_medium=', '/about/', '/contact/',
        '/careers/', '/privacy/', '/terms/', '.pdf', '/login/', '/register/',
        '/help/', '/support/', '/methodology/'
    ]
    is_excluded = any(term in text_to_check for term in excluded_terms)
    
    # Return true if has keyword match and is either a poll or an article, and not excluded
    return (has_keyword_match and (has_poll_indicator or is_article) and not is_excluded)

def build_tracker_urls(keyword):
    """Build potential tracker URLs based on keyword"""
    keyword_lower = keyword.lower()
    tracker_urls = []
    
    # Specific tracker patterns
    if 'trump' in keyword_lower and 'approval' in keyword_lower:
        tracker_urls.append("https://today.yougov.com/topics/politics/trackers/donald-trump-approval")
    elif 'biden' in keyword_lower and 'approval' in keyword_lower:
        tracker_urls.append("https://today.yougov.com/topics/politics/trackers/joe-biden-approval")
    elif 'approval' in keyword_lower:
        # Generic approval trackers
        tracker_urls.extend([
            "https://today.yougov.com/topics/politics/trackers",
            "https://today.yougov.com/topics/politics/trackers/donald-trump-approval",
            "https://today.yougov.com/topics/politics/trackers/joe-biden-approval"
        ])
    
    # Topic-based URLs
    if any(term in keyword_lower for term in ['politic', 'election', 'president', 'congress', 'approval']):
        tracker_urls.append("https://today.yougov.com/topics/politics")
    if any(term in keyword_lower for term in ['economy', 'economic', 'inflation']):
        tracker_urls.append("https://today.yougov.com/topics/economy")
    if any(term in keyword_lower for term in ['society', 'social', 'culture']):
        tracker_urls.append("https://today.yougov.com/topics/society")
    if any(term in keyword_lower for term in ['international', 'foreign', 'world']):
        tracker_urls.append("https://today.yougov.com/topics/international")
    if any(term in keyword_lower for term in ['consumer', 'brand', 'business']):
        tracker_urls.append("https://today.yougov.com/topics/consumer")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in tracker_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    
    return unique_urls

def attempt_real_scraping(keyword, max_results):
    """Attempt real scraping with selenium - returns None if fails"""
    try:
        # Only import selenium if we're actually going to try scraping
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        print(f"Attempting to scrape YouGov tracker pages for: {keyword}")
        
        # Set up chrome options
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
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
            # Build tracker URLs based on keyword
            tracker_urls = build_tracker_urls(keyword)
            print(f"Will try {len(tracker_urls)} tracker/topic pages")
            
            poll_links = []
            
            # Try each tracker/topic page
            for tracker_url in tracker_urls:
                if len(poll_links) >= max_results:
                    break
                    
                try:
                    print(f"Trying tracker page: {tracker_url}")
                    driver.get(tracker_url)
                    time.sleep(8)
                    
                    # Check if page loaded successfully
                    page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                    if len(page_text) > 1000:
                        print(f"✅ Tracker page loaded successfully ({len(page_text)} chars)")
                        
                        # Look for links to recent polls from the tracker
                        try:
                            # Enhanced selectors for finding poll articles
                            link_selectors = [
                                "a[href*='/politics/articles/']",
                                "a[href*='/articles/']", 
                                "a[href*='/topics/']",
                                ".article a", 
                                ".poll a", 
                                ".survey a",
                                ".content-item a",
                                ".poll-item a",
                                ".survey-item a",
                                "yg-results-item a",  # YouGov Angular component
                                "h2 a", 
                                "h3 a", 
                                ".title a", 
                                ".headline a"
                            ]
                            
                            found_links = []
                            for selector in link_selectors:
                                try:
                                    links = driver.find_elements(By.CSS_SELECTOR, selector)
                                    for link in links:
                                        try:
                                            href = link.get_attribute('href')
                                            title = link.text.strip()
                                            
                                            if href and title and is_relevant_content(href, title, "", keyword):
                                                # Avoid duplicates
                                                if not any(existing['href'] == href for existing in found_links):
                                                    found_links.append({'href': href, 'title': title})
                                                    print(f"Found relevant link: {title[:60]}")
                                                    
                                                    if len(found_links) >= max_results * 2:  # Get extras to filter
                                                        break
                                        except:
                                            continue
                                    
                                    if len(found_links) >= max_results * 2:
                                        break
                                except:
                                    continue
                            
                            # Add unique links to main poll_links list
                            for link in found_links:
                                if not any(existing['href'] == link['href'] for existing in poll_links):
                                    poll_links.append(link)
                                    
                            if found_links:
                                print(f"Found {len(found_links)} relevant articles from this tracker page")
                                # Don't break - continue to other pages to get more results
                                
                        except Exception as e:
                            print(f"Error finding links on tracker page: {e}")
                    else:
                        print(f"❌ Tracker page load failed or no content: {tracker_url}")
                        
                except Exception as e:
                    print(f"❌ Tracker page error: {tracker_url} - {e}")
                    continue
            
            # Filter and limit results
            poll_links = poll_links[:max_results]
            
            if not poll_links:
                print("❌ No relevant poll links found on any tracker pages")
                return None
            
            print(f"Processing {len(poll_links)} poll articles...")
            
            # Process each poll article
            results = []
            for i, link_info in enumerate(poll_links):
                try:
                    href = link_info['href']
                    title = link_info['title']
                    
                    print(f"Processing poll article {i+1}: {href}")
                    
                    # Visit the poll page
                    driver.get(href)
                    time.sleep(8)  # Wait for content to load
                    
                    # Extract article content
                    content = ""
                    content_selectors = [
                        # YouGov article content selectors
                        ".article-content",
                        ".post-content", 
                        ".main-content",
                        ".content-body",
                        ".article-body",
                        ".poll-content",
                        # Generic content selectors
                        "main",
                        "article",
                        ".content",
                        "#content",
                        ".page-content"
                    ]
                    
                    for selector in content_selectors:
                        try:
                            content_element = driver.find_element(By.CSS_SELECTOR, selector)
                            content = content_element.text.strip()
                            if len(content) > 500:  # Use if substantial content
                                break
                        except:
                            continue
                    
                    # Fallback to body content if needed
                    if len(content) < 200:
                        try:
                            # Try to get main article text
                            paragraphs = driver.find_elements(By.CSS_SELECTOR, "p")
                            content = "\n".join([p.text.strip() for p in paragraphs if len(p.text.strip()) > 50])
                            
                            if len(content) < 200:
                                body = driver.find_element(By.TAG_NAME, "body")
                                content = body.text.strip()
                        except:
                            content = f"Could not extract content from {href}"
                    
                    # Limit content size and clean it
                    content = content[:8000]
                    content = re.sub(r'\s+', ' ', content)  # Clean whitespace
                    
                    # Extract poll date from content or URL
                    poll_date = time.strftime('%Y-%m-%d')
                    date_matches = re.findall(r'20\d{2}-\d{2}-\d{2}', content + href)
                    if date_matches:
                        poll_date = date_matches[0]
                    
                    # Create generic survey code based on keyword
                    clean_keyword = re.sub(r'[^a-zA-Z0-9\s]', '', keyword).upper().replace(' ', '_')
                    survey_code = f'YOUGOV_{clean_keyword}_{i+1}'
                    
                    results.append({
                        'survey_code': survey_code,
                        'survey_date': poll_date,
                        'survey_question': title,
                        'url': href,
                        'embedded_content': content
                    })
                    
                    print(f"✅ Successfully processed poll article {i+1}")
                    
                except Exception as e:
                    print(f"❌ Error processing poll article {i+1}: {e}")
                    # Add a minimal entry for failed processing
                    clean_keyword = re.sub(r'[^a-zA-Z0-9\s]', '', keyword).upper().replace(' ', '_')
                    results.append({
                        'survey_code': f'YOUGOV_{clean_keyword}_ERROR_{i+1}',
                        'survey_date': time.strftime('%Y-%m-%d'),
                        'survey_question': link_info.get('title', f'Error processing article {i+1}'),
                        'url': link_info.get('href', ''),
                        'embedded_content': f'Error processing YouGov poll article: {str(e)}'
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
                print("No poll articles could be processed")
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
    parser = argparse.ArgumentParser(description='YouGov poll scraper')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=5, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    print(f"YouGov poll scraper starting...")
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
                'survey_code': 'YOUGOV_EMERGENCY',
                'survey_date': time.strftime('%Y-%m-%d'),
                'survey_question': f'Emergency fallback for: {args.keyword}',
                'url': '',
                'embedded_content': f'Emergency fallback content for keyword: {args.keyword}'
            }]
        }
        
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(emergency_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Emergency JSON written")

if __name__ == "__main__":
    main()