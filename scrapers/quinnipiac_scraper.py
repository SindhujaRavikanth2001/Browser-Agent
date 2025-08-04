"""
Quinnipiac University Poll Scraper
Scrapes search results from poll.qu.edu
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
import time
class ScraperTimeout(Exception):
    """Custom exception for scraper timeouts"""
    pass

def run_with_timeout(self, timeout_seconds=300):
    """Run scraper with timeout protection"""
    import signal
    
    def timeout_handler(signum, frame):
        raise ScraperTimeout(f"Scraper timed out after {timeout_seconds} seconds")
    
    # Set timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    
    try:
        # Run your scraping logic here
        self.search_and_scrape(self.keyword, self.max_results)
    finally:
        # Disable timeout
        signal.alarm(0)

class QuinnipiacPollScraper:
    def __init__(self, headless=True):
        self.driver = None
        self.results = []
        self.setup_driver(headless)
    
    def setup_driver(self, headless=True):
        """Initialize Chrome driver"""
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.driver.implicitly_wait(15)
    
    def search_and_scrape(self, search_term, max_results=10):
        """Main scraping function"""
        try:
            # Step 1: Navigate to the search URL
            search_url = f"https://poll.qu.edu/search/#?cludoquery={search_term.replace(' ', '%20')}&cludoType=Poll%20Releases&cludosort=Date_date%3Ddesc&cludopage=1&cludorefurl=https%3A%2F%2Fpoll.qu.edu%2F&cludorefpt=Home%20Page%20%7C%20Quinnipiac%20University%20Poll&cludoinputtype=standard"
            
            print(f"Navigating to: {search_url}")
            self.driver.get(search_url)
            time.sleep(8)  # Give time for JavaScript to load
            
            # Step 2: Wait for Cludo search results to load
            print("Waiting for Cludo search results to load...")
            try:
                WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".cludo-result, [data-cludo-result], .search-result-item"))
                )
                print("Cludo search results loaded")
                time.sleep(5)  # Additional wait for all results to render
            except:
                print("Cludo results not found, trying manual search...")
                try:
                    search_box = self.driver.find_element(By.CSS_SELECTOR, "input[type='search'], .search-input, #search")
                    search_box.clear()
                    search_box.send_keys(search_term)
                    search_box.send_keys(Keys.RETURN)
                    time.sleep(8)
                except:
                    print("Could not perform manual search either")
            
            # Step 3: Collect all poll URLs and their info from search results
            print("Collecting all poll URLs from search results...")
            poll_info_list = self.collect_all_poll_info(max_results)
            
            if not poll_info_list:
                print("No poll URLs found!")
                self.save_debug_info()
                return
            
            print(f"Collected {len(poll_info_list)} poll URLs")
            
            # Step 4: Visit each poll URL and scrape content
            for i, poll_info in enumerate(poll_info_list, 1):
                try:
                    print(f"\n--- Processing poll {i}/{len(poll_info_list)} ---")
                    print(f"Title: {poll_info['title']}")
                    print(f"Date: {poll_info['date']}")
                    print(f"URL: {poll_info['url']}")
                    
                    # Navigate directly to the poll page
                    self.driver.get(poll_info['url'])
                    time.sleep(4)
                    
                    # Scrape the content from the poll page
                    content = self.scrape_poll_content(poll_info)
                    self.results.append(content)
                    
                    print(f"✓ Poll {i} scraped successfully")
                    time.sleep(3)  # Be respectful between requests
                    
                except Exception as e:
                    print(f"✗ Error processing poll {i}: {e}")
                    continue
            
            # Step 5: Save results
            self.save_results_json(search_term)
            print(f"\nScraping completed! Successfully processed {len(self.results)} polls.")
            
        except Exception as e:
            print(f"Error in main scraping: {e}")
            self.save_debug_info()
    
    def collect_all_poll_info(self, max_results):
        """Collect all poll URLs and basic info from search results page"""
        try:
            poll_info_list = []
            
            # Find all search result elements
            result_elements = self.find_cludo_results()
            
            if not result_elements:
                return []
            
            print(f"Found {len(result_elements)} search result elements")
            
            # Process each result element to collect URL and info
            for i, result_element in enumerate(result_elements[:max_results], 1):
                try:
                    print(f"Collecting info from result {i}...")
                    
                    # Extract basic info
                    result_info = self.extract_cludo_result_info(result_element)
                    
                    # Find the clickable link
                    clickable_link = self.find_cludo_clickable_link(result_element)
                    
                    if clickable_link:
                        poll_url = clickable_link.get_attribute('href')
                        
                        if poll_url and 'poll-release' in poll_url:
                            poll_info = {
                                'position': i,
                                'title': result_info['title'],
                                'date': result_info['date'],
                                'snippet': result_info['snippet'],
                                'url': poll_url
                            }
                            poll_info_list.append(poll_info)
                            print(f"  ✓ Collected: {result_info['title'][:60]}...")
                        else:
                            print(f"  ✗ Invalid URL: {poll_url}")
                    else:
                        print(f"  ✗ No clickable link found")
                        
                except Exception as e:
                    print(f"  ✗ Error collecting info from result {i}: {e}")
                    continue
            
            print(f"\nSuccessfully collected {len(poll_info_list)} poll URLs")
            return poll_info_list
            
        except Exception as e:
            print(f"Error collecting poll info: {e}")
            return []
    
    def find_cludo_results(self):
        """Find Cludo search result elements specifically"""
        try:
            # Wait a bit more for dynamic content
            time.sleep(5)
            
            # The exact structure from the HTML you provided
            primary_selectors = [
                "li[class*='border-t']",  # The main li elements containing results
                "a[data-cludo-result='searchresult']",  # Direct link elements
                "[data-cludo-result]",  # Any element with cludo result attribute
                "li a[href*='poll-release']"  # Poll release links in li elements
            ]
            
            for selector in primary_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements and len(elements) >= 3:
                        print(f"Found {len(elements)} results with selector: {selector}")
                        
                        # If we found li elements, extract the links from them
                        if selector.startswith("li"):
                            links = []
                            for li in elements:
                                try:
                                    link = li.find_element(By.CSS_SELECTOR, "a[href*='poll-release']")
                                    if link:
                                        links.append(link)
                                except:
                                    continue
                            if links:
                                print(f"Extracted {len(links)} links from li elements")
                                return links
                        else:
                            return elements
                except Exception as e:
                    print(f"Selector {selector} failed: {e}")
                    continue
            
            # Fallback: look for the specific structure
            try:
                print("Looking for poll release links specifically...")
                poll_links = self.driver.find_elements(By.XPATH, 
                    "//a[contains(@href, 'poll-release') and contains(@href, 'releaseid')]")
                
                if poll_links:
                    print(f"Found {len(poll_links)} poll release links")
                    return poll_links[:15]
            except:
                pass
            
            # Last resort: look in search results containers
            try:
                print("Looking in search results containers...")
                containers = self.driver.find_elements(By.CSS_SELECTOR, 
                    ".search-results, #search-results, .results-container, ul, ol")
                
                for container in containers:
                    links = container.find_elements(By.CSS_SELECTOR, "a[href*='poll-release']")
                    if links and len(links) >= 3:
                        print(f"Found {len(links)} poll links in container")
                        return links[:15]
            except:
                pass
            
            return []
            
        except Exception as e:
            print(f"Error finding Cludo results: {e}")
            return []
    
    def extract_cludo_result_info(self, result_element):
        """Extract information from Cludo search result element"""
        try:
            title = "Unknown Title"
            date = "Unknown Date"
            snippet = ""
            
            # If result_element is a link, get its parent li for full context
            if result_element.tag_name == 'a':
                try:
                    parent_li = result_element.find_element(By.XPATH, "./ancestor::li")
                    context_element = parent_li
                except:
                    context_element = result_element
            else:
                context_element = result_element
            
            # Extract title from the link or data attributes
            try:
                # Method 1: From data-cludo-title attribute
                title_attr = result_element.get_attribute('data-cludo-title')
                if title_attr and len(title_attr) > 10:
                    title = title_attr
                else:
                    # Method 2: From link text or span inside link
                    if result_element.tag_name == 'a':
                        title_text = result_element.text.strip()
                        if len(title_text) > 10:
                            title = title_text
                    else:
                        # Method 3: Find h2 link in the context
                        try:
                            h2_link = context_element.find_element(By.CSS_SELECTOR, "h2 a")
                            title = h2_link.text.strip()
                        except:
                            pass
            except:
                pass
            
            # Extract date from time element
            try:
                time_elem = context_element.find_element(By.CSS_SELECTOR, "time")
                date = time_elem.text.strip()
                if not date:
                    date = time_elem.get_attribute('datetime')
            except:
                # Fallback: look for date patterns in text
                try:
                    date_patterns = context_element.find_elements(By.XPATH, 
                        ".//*[contains(text(), '2025') or contains(text(), '2024') or contains(text(), '2023')]")
                    for elem in date_patterns:
                        text = elem.text.strip()
                        if len(text) < 50 and any(month in text for month in 
                            ['January', 'February', 'March', 'April', 'May', 'June',
                             'July', 'August', 'September', 'October', 'November', 'December']):
                            date = text
                            break
                except:
                    pass
            
            # Extract snippet from text-region div
            try:
                text_region = context_element.find_element(By.CSS_SELECTOR, ".text-region")
                snippet_text = text_region.text.strip()
                if len(snippet_text) > 20:
                    snippet = snippet_text[:400]  # Get more snippet text
            except:
                # Fallback: get any paragraph text
                try:
                    paragraphs = context_element.find_elements(By.TAG_NAME, "p")
                    for p in paragraphs:
                        p_text = p.text.strip()
                        if len(p_text) > len(snippet) and len(p_text) > 20:
                            snippet = p_text[:400]
                except:
                    pass
            
            return {
                'title': title,
                'date': date,
                'snippet': snippet
            }
            
        except Exception as e:
            print(f"Error extracting Cludo result info: {e}")
            return {'title': 'Unknown', 'date': 'Unknown', 'snippet': ''}
    
    def find_cludo_clickable_link(self, result_element):
        """Find the main clickable link in a Cludo search result"""
        try:
            # If the element itself is already a poll-release link
            if (result_element.tag_name == 'a' and 
                result_element.get_attribute('href') and 
                'poll-release' in result_element.get_attribute('href')):
                return result_element
            
            # Look for poll-release link within the element
            link_selectors = [
                "a[href*='poll-release']",
                "h2 a",
                "a[data-cludo-result]",
                ".heading-6 a",
                "a[data-cludo-url]"
            ]
            
            for selector in link_selectors:
                try:
                    link = result_element.find_element(By.CSS_SELECTOR, selector)
                    href = link.get_attribute('href')
                    if href and 'poll-release' in href and 'releaseid' in href:
                        print(f"Found poll release link: {href}")
                        return link
                except:
                    continue
            
            return None
            
        except Exception as e:
            print(f"Error finding Cludo clickable link: {e}")
            return None
    
    def scrape_poll_content(self, result_info):
        """Scrape content from the poll page"""
        try:
            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            current_url = self.driver.current_url
            page_title = self.driver.title
            
            # Extract main content using various selectors
            content_selectors = [
                ".entry-content",
                ".post-content", 
                ".content",
                "main",
                "article",
                ".poll-content",
                ".release-content",
                "#content",
                ".page-content"
            ]
            
            main_content = ""
            for selector in content_selectors:
                try:
                    content_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    text = content_element.text.strip()
                    if len(text) > len(main_content):
                        main_content = text
                except:
                    continue
            
            # If no main content found, get body text
            if not main_content:
                try:
                    body = self.driver.find_element(By.TAG_NAME, "body")
                    main_content = body.text.strip()
                except:
                    main_content = "Could not extract content"
            
            # Look for poll data tables
            tables_content = ""
            try:
                tables = self.driver.find_elements(By.TAG_NAME, "table")
                for table in tables:
                    table_text = table.text.strip()
                    if len(table_text) > 50:
                        tables_content += f"\n--- POLL DATA TABLE ---\n{table_text}\n"
            except:
                pass
            
            # Look for poll methodology or additional info
            methodology = ""
            try:
                method_selectors = [".methodology", ".method", "[class*='method']", ".footnote"]
                for selector in method_selectors:
                    try:
                        method_elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                        methodology = method_elem.text.strip()
                        break
                    except:
                        continue
            except:
                pass
            
            return {
                'original_title': result_info['title'],
                'original_date': result_info['date'],
                'original_snippet': result_info['snippet'],
                'page_title': page_title,
                'url': current_url,
                'main_content': main_content[:8000],  # Limit content length
                'tables_content': tables_content[:3000],
                'methodology': methodology[:1000],
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            print(f"Error scraping poll content: {e}")
            return {
                'original_title': result_info['title'],
                'original_date': result_info['date'],
                'original_snippet': result_info['snippet'],
                'page_title': 'Error',
                'url': self.driver.current_url,
                'main_content': f'Error scraping content: {str(e)}',
                'tables_content': '',
                'methodology': '',
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
    
    def save_debug_info(self):
        """Save debug information when scraping fails"""
        try:
            self.driver.save_screenshot("quinnipiac_debug.png")
            with open("quinnipiac_debug.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            print("Debug files saved: quinnipiac_debug.png and quinnipiac_debug.html")
        except Exception as e:
            print(f"Could not save debug info: {e}")
    
    def save_results_json(self, keyword, output_file):
        """Save results in JSON format for integration"""
        output_data = {
            'keyword': keyword,
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_results': len(self.results),
            'surveys': []
        }
        
        for result in self.results:
            survey_data = {
                'survey_code': result.get('survey_code', result.get('original_title', 'Unknown')),
                'survey_date': result.get('survey_date', result.get('original_date', 'Unknown')),
                'survey_question': result.get('survey_question', result.get('main_content', '')[:500]),
                'embedded_content': result.get('embedded_content', result.get('main_content', '')),
                'url': result.get('url', ''),
                'extracted_questions': self.extract_questions_from_result(result)
            }
            output_data['surveys'].append(survey_data)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

    def extract_questions_from_result(self, result):
        """Extract questions from a single result"""
        content = result.get('embedded_content', result.get('main_content', ''))
        return extract_questions_from_content(content)
    
    def cleanup(self):
        """Close browser"""
        if self.driver:
            self.driver.quit()
            print("Browser closed")

def main():
    """Run the scraper with command line arguments"""
    parser = argparse.ArgumentParser(description='Poll scraper')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=10, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    headless = args.headless.lower() == 'true'
    
    scraper = QuinnipiacPollScraper(headless=headless)  # Replace with actual class name
    
    try:
        scraper.search_and_scrape(args.keyword, args.max_results)
        
        # Convert results to the expected format and save as JSON
        output_data = {
            'keyword': args.keyword,
            'max_results': args.max_results,
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'surveys': []
        }
        
        # Process your results and add them to surveys
        for result in scraper.results:
            survey_data = {
                'survey_code': result.get('survey_code', 'Unknown'),
                'survey_date': result.get('survey_date', 'Unknown'),
                'survey_question': result.get('survey_question', ''),
                'embedded_content': result.get('embedded_content', ''),
                'extracted_questions': extract_questions_from_content(result.get('embedded_content', ''))
            }
            output_data['surveys'].append(survey_data)
        
        # Save to JSON file
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"Results saved to {args.output}")
        
    finally:
        scraper.cleanup()

def extract_questions_from_content(content):
    """Extract individual questions from content"""
    if not content:
        return []
    
    questions = []
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        # Look for lines that end with '?' and have reasonable length
        if line.endswith('?') and 20 <= len(line) <= 200:
            # Clean up the line
            clean_line = re.sub(r'^\d+[\.\)]\s*', '', line)  # Remove numbering
            clean_line = re.sub(r'^[-•*]\s*', '', clean_line)  # Remove bullets
            clean_line = clean_line.strip()
            
            if clean_line and len(clean_line) > 20:
                questions.append(clean_line)
    
    return questions[:10]  # Limit to 10 questions per survey

if __name__ == "__main__":
    main()