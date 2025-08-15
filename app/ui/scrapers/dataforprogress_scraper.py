"""
Data for Progress Poll Scraper - GENERIC VERSION
Scrapes polls from dataforprogress.org for any keyword
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
            'survey_code': 'DFP_MINIMAL',
            'survey_date': time.strftime('%Y-%m-%d'),
            'survey_question': f'Data for Progress poll search for: {keyword}',
            'url': f'https://www.dataforprogress.org/find?q={urllib.parse.quote(keyword)}',
            'embedded_content': f'Minimal Data for Progress scraper result for keyword: {keyword}. This is a placeholder result to ensure the polling system works. The actual Data for Progress website may require more sophisticated scraping techniques or may be blocking automated access.'
        }]
    }

def build_search_urls(keyword):
    """Build search URLs for Data for Progress"""
    search_urls = []
    
    # Main search URL (Google Custom Search)
    main_search = f"https://www.dataforprogress.org/find?q={urllib.parse.quote(keyword)}"
    search_urls.append(main_search)
    
    # Alternative search formats
    keyword_encoded = urllib.parse.quote_plus(keyword)
    search_urls.extend([
        f"https://www.dataforprogress.org/search?q={keyword_encoded}",
        f"https://www.dataforprogress.org/?s={keyword_encoded}",
    ])
    
    # Try homepage and common research pages
    search_urls.extend([
        "https://www.dataforprogress.org/",
        "https://www.dataforprogress.org/polls/",
        "https://www.dataforprogress.org/research/",
        "https://www.dataforprogress.org/surveys/",
        "https://www.dataforprogress.org/blog/",
        "https://www.dataforprogress.org/memos/",
        "https://www.dataforprogress.org/reports/"
    ])
    
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in search_urls:
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
        
        print(f"Attempting to scrape Data for Progress for: {keyword}")
        
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
                if len(poll_links) >= max_results:
                    break
                    
                try:
                    print(f"Trying search page: {search_url}")
                    driver.get(search_url)
                    time.sleep(10)  # Longer wait for Google Custom Search to load
                    
                    # Wait for search results or content to load
                    try:
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".gsc-results, .search-results, .content, .post, .entry"))
                        )
                        print("Search results or content loaded")
                    except:
                        print("Proceeding without specific result indicators...")
                        
                    # Additional wait for dynamic content
                    time.sleep(5)
                    
                    # Check if page loaded successfully
                    page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                    if len(page_text) > 500:
                        print(f"✅ Search page loaded successfully ({len(page_text)} chars)")
                        
                        # Look for links to research articles
                        try:
                            # Enhanced selectors for finding research articles
                            link_selectors = [
                                # Google Custom Search results
                                ".gsc-results a",
                                ".gsc-result a", 
                                ".gs-result a",
                                ".gsc-thumbnail-inside a",
                                ".gsc-url-top a",
                                # Data for Progress specific selectors
                                "a[href*='dataforprogress.org']",
                                ".post a", 
                                ".entry a", 
                                ".article a", 
                                ".content a",
                                ".blog-post a",
                                ".memo a",
                                ".poll a",
                                ".survey a",
                                ".research a",
                                # Generic content selectors
                                "h1 a", 
                                "h2 a", 
                                "h3 a", 
                                ".title a", 
                                ".headline a",
                                ".post-title a",
                                ".entry-title a",
                                ".summary a"
                            ]
                            
                            found_links = []
                            for selector in link_selectors:
                                try:
                                    links = driver.find_elements(By.CSS_SELECTOR, selector)
                                    for link in links:
                                        try:
                                            href = link.get_attribute('href')
                                            title = link.text.strip()
                                            
                                            if href and title and 'dataforprogress.org' in href:
                                                # STRICT filtering for actual research content
                                                is_research_related = False
                                                
                                                # Must have substantial link text (not just navigation)
                                                if len(title) < 20:
                                                    is_research_related = False
                                                else:
                                                    # Look for specific research content indicators
                                                    research_indicators_strong = [
                                                        'poll', 'survey', 'study', 'findings', 'analysis', 'report',
                                                        'memo', 'data', 'research', 'polling'
                                                    ]
                                                    
                                                    url_has_research = any(indicator in href.lower() for indicator in research_indicators_strong)
                                                    text_has_research = any(indicator in title.lower() for indicator in research_indicators_strong)
                                                    
                                                    # Look for date patterns in URL (actual articles have dates)
                                                    has_date_pattern = re.search(r'/20\d{2}/', href) or re.search(r'-20\d{2}-', href)
                                                    
                                                    # Look for very specific research content patterns
                                                    specific_patterns = [
                                                        'americans-', 'voters-', 'polling-', 'survey-finds', 'memo-',
                                                        'research-', 'data-shows', 'poll-finds', '/blog/', '/memos/'
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
                                                        '/team/', '/staff/', '/join/', '/donate/', '/support/',
                                                        '/methodology/', '.pdf', '.doc', '.jpg', '.png', 
                                                        '/wp-admin/', '/wp-content/', '/feed/', '/category/', 
                                                        '/page/', 'mailto:', '/leadership/', '/board/',
                                                        'facebook.com', 'twitter.com', 'linkedin.com'
                                                    ]) or
                                                    # Exclude if it's just a navigation page
                                                    title.lower() in [
                                                        'about', 'contact', 'team', 'careers', 'donate', 'home'
                                                    ] or
                                                    # Exclude very short URLs (likely navigation)
                                                    len(href.split('/')) <= 4
                                                )
                                                
                                                if is_research_related and not is_excluded:
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
                                print(f"Found {len(found_links)} relevant articles from this search page")
                                
                        except Exception as e:
                            print(f"Error finding links on search page: {e}")
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
                        print(f"Collected research {i+1}: {title[:60]} -> {href}")
                except Exception as e:
                    print(f"Error collecting link {i}: {e}")
                    continue
            
            # If no research links found, try to find actual articles on homepage/blog pages
            if not link_data:
                print("No specific research links found, looking for recent articles...")
                
                # Try homepage and blog page for recent content
                try:
                    for fallback_url in ["https://www.dataforprogress.org/", "https://www.dataforprogress.org/blog/"]:
                        if len(link_data) >= max_results:
                            break
                            
                        print(f"Checking {fallback_url} for recent articles...")
                        driver.get(fallback_url)
                        time.sleep(8)
                        
                        # Look for recent articles/posts
                        article_selectors = [
                            ".post", ".entry", ".article", ".blog-post", 
                            ".memo", ".poll-result", ".research-item"
                        ]
                        
                        for selector in article_selectors:
                            try:
                                articles = driver.find_elements(By.CSS_SELECTOR, selector)
                                for article in articles[:max_results]:
                                    try:
                                        # Find link within article
                                        article_link = article.find_element(By.CSS_SELECTOR, "a[href*='dataforprogress.org']")
                                        href = article_link.get_attribute('href')
                                        
                                        # Get article title
                                        title_elem = article.find_element(By.CSS_SELECTOR, "h1, h2, h3, .title, .post-title, .entry-title")
                                        title = title_elem.text.strip()
                                        
                                        # Only add if it looks like substantial content
                                        if (href and title and len(title) > 30 and
                                            not any(exclude in href.lower() for exclude in [
                                                '/about/', '/contact/', '/team/', '/donate/'
                                            ]) and
                                            len(href.split('/')) > 4):
                                            
                                            link_data.append({'href': href, 'title': title})
                                            print(f"Found recent article: {title[:50]}")
                                            
                                            if len(link_data) >= max_results:
                                                break
                                    except:
                                        continue
                                        
                                if len(link_data) >= max_results:
                                    break
                            except:
                                continue
                                
                except Exception as e:
                    print(f"Error finding recent articles: {e}")
                
                # If still no links, create debug info
                if not link_data:
                    print("Still no articles found. Debug info:")
                    try:
                        page_text_sample = driver.find_element(By.TAG_NAME, "body").text.lower()
                        
                        if any(phrase in page_text_sample for phrase in [
                            'no results', 'nothing found', 'no posts found', 'no matches'
                        ]):
                            print("❌ Search returned no results for this keyword")
                        else:
                            print(f"Page contains {len(page_text_sample)} characters but no extractable research links")
                            print(f"Sample content: {page_text_sample[:500]}")
                        
                    except Exception as debug_e:
                        print(f"Debug failed: {debug_e}")
            
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
                        # Data for Progress specific content selectors
                        ".post-content",
                        ".entry-content",
                        ".article-content",
                        ".content",
                        ".main-content",
                        ".blog-content",
                        ".memo-content",
                        ".poll-content",
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
                        'survey_code': f'DFP_{clean_keyword}_{i+1}',
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
                        'survey_code': f'DFP_{clean_keyword}_{i+1}_ERROR',
                        'survey_date': time.strftime('%Y-%m-%d'),
                        'survey_question': link_info.get('title', f'Error processing page {i+1}'),
                        'url': link_info.get('href', ''),
                        'embedded_content': f'Error processing this Data for Progress page: {str(e)}'
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
    parser = argparse.ArgumentParser(description='Data for Progress poll scraper')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=5, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    print(f"Data for Progress poll scraper starting...")
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
                'survey_code': 'DFP_EMERGENCY',
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