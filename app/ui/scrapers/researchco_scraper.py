"""
Research Co. Poll Scraper - SINGLE URL VERSION
Scrapes polls from researchco.ca for any keyword using only one search URL
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
            'survey_code': 'RESEARCHCO_MINIMAL',
            'survey_date': time.strftime('%Y-%m-%d'),
            'survey_question': f'Research Co. poll search for: {keyword}',
            'url': f'https://researchco.ca/?s={urllib.parse.quote(keyword)}',
            'embedded_content': f'Minimal Research Co. scraper result for keyword: {keyword}. This is a placeholder result to ensure the polling system works. The actual Research Co. website may require more sophisticated scraping techniques or may be blocking automated access.'
        }]
    }

def get_single_search_url(keyword):
    """Get the main search URL for Research Co."""
    return f"https://researchco.ca/?s={urllib.parse.quote(keyword)}"

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
        'poll', 'survey', 'study', 'research', 'research co', 'researchco', 
        'polling', 'rating', 'opinion', 'favorability', 'unfavorability', 
        'popularity', 'tracking', 'data', 'findings', 'analysis'
    ]
    has_poll_indicator = any(indicator in text_to_check for indicator in poll_indicators)
    
    # Check for relevant URL patterns
    relevant_patterns = [
        'researchco.ca', '/poll', '/survey', '/research', '/data',
        '/analysis', '/findings', '/report'
    ]
    is_relevant_url = any(pattern in text_to_check for pattern in relevant_patterns)
    
    # Exclude non-content pages
    excluded_terms = [
        '/about/', '/contact/', '/team/', '/careers/', '/privacy/',
        '/terms/', '.pdf', '/login/', '/register/', '/help/',
        '/support/', '/methodology/', 'utm_source=', 'utm_medium='
    ]
    is_excluded = any(term in text_to_check for term in excluded_terms)
    
    # Return true if has keyword match and is either a poll or relevant URL, and not excluded
    return (has_keyword_match and (has_poll_indicator or is_relevant_url) and not is_excluded)

def attempt_real_scraping(keyword, max_results):
    """Attempt real scraping with selenium - returns None if fails"""
    try:
        # Only import selenium if we're actually going to try scraping
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        print(f"Attempting to scrape Research Co. for: {keyword}")
        
        # Set up chrome options
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        # Try to create driver
        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            print(f"Chrome driver failed: {e}")
            return None
        
        try:
            # Use single search URL
            search_url = get_single_search_url(keyword)
            print(f"Using single search URL: {search_url}")
            
            poll_links = []
            
            try:
                print(f"Accessing search page: {search_url}")
                driver.get(search_url)
                time.sleep(8)
                
                # Check if page loaded successfully
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                if len(page_text) > 500:
                    print(f"✅ Search page loaded successfully ({len(page_text)} chars)")
                    
                    # Look for links to research articles
                    try:
                        # Enhanced selectors for finding research articles
                        link_selectors = [
                            # WordPress/general selectors
                            "a[href*='researchco.ca']",
                            ".post a", 
                            ".entry a", 
                            ".article a", 
                            ".content a",
                            ".search-results a",
                            ".post-title a",
                            ".entry-title a",
                            ".entry-header a",
                            # Generic content selectors
                            "h1 a", 
                            "h2 a", 
                            "h3 a", 
                            ".title a", 
                            ".headline a",
                            ".summary a",
                            # Research-specific selectors
                            ".research a",
                            ".poll a",
                            ".survey a",
                            ".study a",
                            ".report a",
                            ".findings a"
                        ]
                        
                        found_links = []
                        for selector in link_selectors:
                            try:
                                links = driver.find_elements(By.CSS_SELECTOR, selector)
                                for link in links:
                                    try:
                                        href = link.get_attribute('href')
                                        title = link.text.strip()
                                        
                                        if href and title and 'researchco.ca' in href:
                                            # STRICT filtering for actual research content
                                            is_research_related = False
                                            
                                            # Must have substantial link text (not just navigation)
                                            if len(title) < 20:
                                                is_research_related = False
                                            else:
                                                # Look for specific research content indicators
                                                research_indicators_strong = [
                                                    'poll', 'survey', 'study', 'findings', 'analysis', 'report'
                                                ]
                                                
                                                url_has_research = any(indicator in href.lower() for indicator in research_indicators_strong)
                                                text_has_research = any(indicator in title.lower() for indicator in research_indicators_strong)
                                                
                                                # Look for date patterns in URL (actual articles have dates)
                                                has_date_pattern = re.search(r'/20\d{2}/', href) or re.search(r'-20\d{2}-', href)
                                                
                                                # Look for very specific research content patterns
                                                specific_patterns = [
                                                    'canadians-', 'voters-', 'polling-', 'survey-finds', 'study-shows',
                                                    'research-reveals', 'data-shows', 'poll-finds'
                                                ]
                                                has_specific_pattern = any(pattern in href.lower() for pattern in specific_patterns)
                                                
                                                # Must meet MULTIPLE criteria for strict filtering
                                                is_research_related = (
                                                    (url_has_research and text_has_research) or  # Both URL and text mention research
                                                    (has_date_pattern and (url_has_research or text_has_research)) or  # Date + research mention
                                                    has_specific_pattern  # Very specific research patterns
                                                )
                                            
                                            # STRICT exclusion list
                                            is_excluded = (
                                                any(exclude in href.lower() for exclude in [
                                                    '/about/', '/contact/', '/careers/', '/privacy/', '/terms/',
                                                    '/search/', '/cookies/', '/legal/', '/team/', '/who-we-are/',
                                                    '/our-work/', '/services/', '/capabilities/', '.pdf', '.doc', 
                                                    '.jpg', '.png', '/media-kit/', '/wp-admin/', '/wp-content/', 
                                                    '/feed/', '/category/', '/page/', 'mailto:', '/staff/', 
                                                    '/leadership/', '/board/'
                                                ]) or
                                                # Exclude if it's just a navigation page
                                                title.lower() in [
                                                    'about', 'contact', 'team', 'careers', 'services', 'home'
                                                ] or
                                                # Exclude very short URLs (likely navigation)
                                                len(href.split('/')) <= 4
                                            )
                                            
                                            if is_research_related and not is_excluded:
                                                # Avoid duplicates
                                                if not any(existing['href'] == href for existing in found_links):
                                                    found_links.append({'href': href, 'title': title})
                                                    print(f"Found relevant link: {title[:60]}")
                                                    
                                                    if len(found_links) >= max_results:
                                                        break
                                    except:
                                        continue
                                
                                if len(found_links) >= max_results:
                                    break
                            except:
                                continue
                        
                        # Add found links to poll_links
                        poll_links = found_links[:max_results]
                        
                        if found_links:
                            print(f"Found {len(found_links)} relevant articles")
                            
                    except Exception as e:
                        print(f"Error finding links: {e}")
                else:
                    print(f"❌ Search page load failed or no content")
                    
            except Exception as e:
                print(f"❌ Search page error: {e}")
            
            # Extract href and title IMMEDIATELY to avoid stale element issues
            link_data = []
            for i, link_info in enumerate(poll_links):
                try:
                    href = link_info['href']
                    title = link_info['title']
                    
                    if href:
                        link_data.append({'href': href, 'title': title})
                        print(f"Collected research {i+1}: {title[:60]} -> {href}")
                except Exception as e:
                    print(f"Error collecting link {i}: {e}")
                    continue
            
            # If no research links found, try to find actual articles on search results page
            if not link_data:
                print("No specific research links found, looking for actual article content...")
                
                # Look for article titles and content on the search results page itself
                try:
                    # Try to find search result entries with substantial content
                    search_entries = driver.find_elements(By.CSS_SELECTOR, ".search-result, .post, .entry, .hentry")
                    
                    for i, entry in enumerate(search_entries[:max_results]):
                        try:
                            # Try to find a link within this entry
                            entry_link = entry.find_element(By.CSS_SELECTOR, "a[href*='researchco.ca']")
                            href = entry_link.get_attribute('href')
                            
                            # Get the entry title/content
                            title_elements = entry.find_elements(By.CSS_SELECTOR, "h1, h2, h3, .title, .entry-title, .post-title")
                            title = ""
                            for title_elem in title_elements:
                                potential_title = title_elem.text.strip()
                                if len(potential_title) > len(title):
                                    title = potential_title
                            
                            # If no good title found, try the link text
                            if not title or len(title) < 20:
                                title = entry_link.text.strip()
                            
                            # Only add if it looks like actual content (long title, specific URL)
                            if (href and title and len(title) > 30 and 
                                'researchco.ca' in href and
                                not any(exclude in href.lower() for exclude in [
                                    '/about/', '/contact/', '/team/', '/category/', '/page/', 'mailto:'
                                ]) and
                                len(href.split('/')) > 4):
                                
                                link_data.append({'href': href, 'title': title})
                                print(f"Found article from search results: {title[:50]}")
                                
                                if len(link_data) >= max_results:
                                    break
                                    
                        except:
                            continue
                            
                except Exception as e:
                    print(f"Error searching for articles in results: {e}")
            
            # Now process the collected links
            results = []
            for i, link_info in enumerate(link_data):
                try:
                    href = link_info['href']
                    title = link_info['title']
                    
                    print(f"Processing research page {i+1}: {href}")
                    
                    # Visit the research page
                    driver.get(href)
                    time.sleep(5)  # Wait for content to load
                    
                    # Try multiple selectors for main content
                    content = ""
                    content_selectors = [
                        # WordPress-specific content selectors
                        ".entry-content",
                        ".post-content",
                        ".content",
                        ".main-content",
                        ".article-content",
                        ".page-content",
                        ".single-content",
                        # Generic content selectors
                        "main",
                        "article",
                        ".container .content",
                        "#content",
                        ".primary .content"
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
                    content = content[:6000]
                    
                    # Create clean keyword for survey code
                    clean_keyword = re.sub(r'[^a-zA-Z0-9\s]', '', keyword).upper().replace(' ', '_')
                    
                    results.append({
                        'survey_code': f'RESEARCHCO_{clean_keyword}_{i+1}',
                        'survey_date': time.strftime('%Y-%m-%d'),
                        'survey_question': title,
                        'url': href,
                        'embedded_content': content
                    })
                    
                    print(f"✅ Successfully processed research page {i+1}")
                    
                    if len(results) >= max_results:
                        break
                        
                except Exception as e:
                    print(f"❌ Error processing research page {i+1}: {e}")
                    # Add a fallback entry even if processing fails
                    clean_keyword = re.sub(r'[^a-zA-Z0-9\s]', '', keyword).upper().replace(' ', '_')
                    results.append({
                        'survey_code': f'RESEARCHCO_{clean_keyword}_{i+1}_ERROR',
                        'survey_date': time.strftime('%Y-%m-%d'),
                        'survey_question': link_info.get('title', f'Error processing page {i+1}'),
                        'url': link_info.get('href', ''),
                        'embedded_content': f'Error processing this Research Co. page: {str(e)}'
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
                print("No research pages found")
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
    parser = argparse.ArgumentParser(description='Research Co. poll scraper - Single URL version')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=5, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    print(f"Research Co. poll scraper starting (Single URL version)...")
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
                'survey_code': 'RESEARCHCO_EMERGENCY',
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