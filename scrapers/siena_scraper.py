"""
Siena Research Institute Scraper
Scrapes search results from sri.siena.edu
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
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

class SienaResearchScraper:
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
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.implicitly_wait(15)
    
    def search_and_scrape(self, keyword, max_results=10):
        """Main scraping function"""
        try:
            # Step 1: Navigate to search results
            search_url = f"https://sri.siena.edu/?s={keyword}"
            print(f"Navigating to: {search_url}")
            
            self.driver.get(search_url)
            time.sleep(5)  # Wait for page to load
            
            # Step 2: Wait for search results to load
            print("Waiting for search results to load...")
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".search-results, .post, article, .entry"))
                )
                print("Search results page loaded")
                time.sleep(2)
            except:
                print("Warning: Could not detect search results elements")
            
            # Step 3: Find search result links
            result_links = self.find_result_links()
            
            if not result_links:
                print("No search result links found!")
                return
            
            print(f"Found {len(result_links)} search result links")
            
            # Step 4: Process each result link
            links_to_process = result_links[:max_results]
            
            for i, link_info in enumerate(links_to_process, 1):
                try:
                    print(f"\n--- Processing result {i}/{len(links_to_process)} ---")
                    print(f"Title: {link_info['title']}")
                    print(f"URL: {link_info['url']}")
                    
                    # Navigate to the result page
                    self.driver.get(link_info['url'])
                    time.sleep(3)
                    
                    # Scrape the content from the page
                    content = self.scrape_page_content(link_info)
                    self.results.append(content)
                    
                    print(f"✓ Result {i} scraped successfully")
                    time.sleep(2)  # Be respectful between requests
                    
                except Exception as e:
                    print(f"✗ Error processing result {i}: {e}")
                    continue
            
            # Step 5: Save results
            self.save_results_json(keyword)
            print(f"\nScraping completed! Successfully processed {len(self.results)} results.")
            
        except Exception as e:
            print(f"Error in main scraping: {e}")
    
    def find_result_links(self):
        """Find all search result links on the page"""
        try:
            result_links = []
            
            # Try different selectors for search results
            link_selectors = [
                # Common WordPress search result selectors
                ".search-results article h2 a",
                ".search-results .entry-title a", 
                ".post .entry-title a",
                ".post h2 a",
                ".post h3 a",
                "article .entry-title a",
                "article h2 a",
                "article h3 a",
                ".entry-header h2 a",
                ".entry-header .entry-title a",
                # Generic selectors
                "h2 a[href*='sri.siena.edu']",
                "h3 a[href*='sri.siena.edu']",
                ".post-title a",
                ".title a"
            ]
            
            for selector in link_selectors:
                try:
                    links = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    
                    for link in links:
                        href = link.get_attribute('href')
                        title = link.text.strip()
                        
                        # Filter valid results
                        if (href and href not in [r['url'] for r in result_links] 
                            and 'sri.siena.edu' in href
                            and len(title) > 5
                            and not href.endswith(('.pdf', '.jpg', '.png', '.doc'))):
                            
                            result_links.append({
                                'url': href,
                                'title': title,
                                'position': len(result_links) + 1
                            })
                    
                    if result_links:
                        print(f"Found {len(result_links)} links with selector: {selector}")
                        break
                        
                except Exception as e:
                    continue
            
            # If no specific search results found, try finding any relevant links
            if not result_links:
                print("No specific search results found, trying general links...")
                try:
                    all_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'sri.siena.edu')]")
                    
                    for link in all_links[:15]:  # Limit to avoid too many
                        href = link.get_attribute('href')
                        title = link.text.strip()
                        
                        if (href and title and len(title) > 10
                            and not href.endswith(('.pdf', '.jpg', '.png'))
                            and 'trump' in title.lower()):
                            
                            result_links.append({
                                'url': href,
                                'title': title,
                                'position': len(result_links) + 1
                            })
                            
                except:
                    pass
            
            return result_links
            
        except Exception as e:
            print(f"Error finding result links: {e}")
            return []
    
    def scrape_page_content(self, link_info):
        """Scrape content from a result page"""
        try:
            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Get page title
            page_title = self.driver.title
            
            # Try different content selectors
            content_selectors = [
                ".entry-content",
                ".post-content", 
                ".content",
                "main",
                "article",
                ".post",
                ".entry",
                "#content",
                ".page-content",
                ".single-content"
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
            
            # Look for any data tables or specific content
            tables_content = ""
            try:
                tables = self.driver.find_elements(By.TAG_NAME, "table")
                for table in tables:
                    table_text = table.text.strip()
                    if len(table_text) > 50:
                        tables_content += f"\n--- TABLE DATA ---\n{table_text}\n"
            except:
                pass
            
            # Get meta description if available
            meta_description = ""
            try:
                meta_desc = self.driver.find_element(By.XPATH, "//meta[@name='description']")
                meta_description = meta_desc.get_attribute('content')
            except:
                pass
            
            return {
                'position': link_info['position'],
                'original_title': link_info['title'],
                'page_title': page_title,
                'url': link_info['url'],
                'meta_description': meta_description,
                'main_content': main_content[:8000],  # Limit content length
                'tables_content': tables_content[:2000],
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            print(f"Error scraping page content: {e}")
            return {
                'position': link_info['position'],
                'original_title': link_info['title'],
                'page_title': 'Error',
                'url': link_info['url'],
                'meta_description': '',
                'main_content': f'Error scraping content: {str(e)}',
                'tables_content': '',
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
    
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
    
    scraper = SienaResearchScraper(headless=headless)  # Replace with actual class name
    
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