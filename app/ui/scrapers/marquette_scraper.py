"""
Simple Marquette Law School Poll Scraper
Step 1: Navigate to search URL
Step 2: Collect URLs of 8 search results  
Step 3: Visit each URL and scrape content
Step 4: Store everything in JSON file
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import argparse
import json
import re
from question_extractor import extract_questions_from_content, question_extractor

class ScraperTimeout(Exception):
    """Custom exception for scraper timeouts"""
    pass

class SimpleMarquetteScraper:
    def __init__(self, headless=True):
        self.driver = None
        self.results = []
        self.setup_driver(headless)
    
    def setup_driver(self, headless=True):
        """Initialize Chrome driver with multiple fallback methods"""
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Try multiple approaches for ChromeDriver
        try:
            # Method 1: Use webdriver-manager (if working)
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            print("✅ ChromeDriver loaded via webdriver-manager")
        except Exception as e:
            print(f"❌ webdriver-manager failed: {e}")
            try:
                # Method 2: Use manually installed ChromeDriver
                service = Service('/usr/local/bin/chromedriver')
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                print("✅ ChromeDriver loaded from /usr/local/bin/chromedriver")
            except Exception as e2:
                print(f"❌ Manual ChromeDriver failed: {e2}")
                try:
                    # Method 3: Let Selenium find ChromeDriver automatically
                    self.driver = webdriver.Chrome(options=chrome_options)
                    print("✅ ChromeDriver loaded automatically by Selenium")
                except Exception as e3:
                    print(f"❌ All ChromeDriver methods failed: {e3}")
                    raise e3
        
        # Set implicit wait and other configurations
        self.driver.implicitly_wait(10)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    def search_and_scrape(self, search_term, max_results=5):
        """Main scraping function - FIXED method name"""
        self.results = []
        
        # Step 1: Navigate to search URL
        search_url = f"https://law.marquette.edu/poll/?s={search_term.replace(' ', '+')}"
        print(f"Step 1: Navigating to {search_url}")
        self.driver.get(search_url)
        time.sleep(5)
        
        # Step 2: Collect URLs of search results
        print("Step 2: Collecting URLs of search results...")
        urls = self.collect_urls(max_results)
        print(f"Found {len(urls)} URLs: {urls}")
        
        # Step 3: Visit each URL and scrape content
        print("Step 3: Visiting each URL and scraping content...")
        for i, url in enumerate(urls[:max_results], 1):
            print(f"  Scraping {i}/{min(len(urls), max_results)}: {url}")
            
            try:
                self.driver.get(url)
                time.sleep(3)
                
                # Get page title
                title = self.driver.title
                
                # Get main content
                content = self.get_page_content()
                
                # Extract questions with enhanced extraction
                extracted_questions = question_extractor.extract_questions_with_metadata(
                    content, url, title
                )
                
                self.results.append({
                    'number': i,
                    'url': url,
                    'title': title,
                    'content': content,
                    'survey_code': f"MARQUETTE_{i}",
                    'survey_date': time.strftime('%Y-%m-%d'),
                    'survey_question': title,
                    'embedded_content': content,
                    'main_content': content,
                    'extracted_questions': extracted_questions
                })
                
                print(f"  ✓ Scraped: {title}")
            except Exception as e:
                print(f"  ❌ Error scraping {url}: {e}")
                continue
        
        print(f"Step 4: Completed scraping {len(self.results)} results")
        return self.results
    
    def collect_urls(self, max_results=5):
        """Collect URLs from search results"""
        urls = []
        
        # Find all article links
        articles = self.driver.find_elements(By.CSS_SELECTOR, "article")
        
        for article in articles[:max_results]:  # Get first max_results
            try:
                link = article.find_element(By.CSS_SELECTOR, "h2 a")
                url = link.get_attribute('href')
                if url and 'law.marquette.edu/poll' in url and '?s=' not in url:
                    urls.append(url)
            except:
                continue
        
        return urls[:max_results]  # Ensure we only get max_results
    
    def get_page_content(self):
        """Get main content from current page"""
        try:
            # Try to get main content
            content_element = self.driver.find_element(By.CSS_SELECTOR, ".entry-content")
            return content_element.text.strip()
        except:
            try:
                # Fallback to body
                body = self.driver.find_element(By.TAG_NAME, "body")
                return body.text.strip()
            except:
                return "Could not extract content"
    
    def extract_questions_from_result(self, result):
        """Extract questions from a single result"""
        content = result.get('embedded_content', result.get('main_content', ''))
        return extract_questions_from_content(content)
    
    def cleanup(self):
        """Close browser"""
        if self.driver:
            self.driver.quit()

# Use the enhanced question extraction from the shared module
# The extract_questions_from_content function is now imported from question_extractor

def main():
    """Run the scraper with command line arguments"""
    parser = argparse.ArgumentParser(description='Poll scraper')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=5, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    headless = args.headless.lower() == 'true'
    
    scraper = SimpleMarquetteScraper(headless=headless)
    
    try:
        results = scraper.search_and_scrape(args.keyword, args.max_results)
        
        # Convert results to the expected format and save as JSON
        output_data = {
            'keyword': args.keyword,
            'max_results': args.max_results,
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'surveys': []
        }
        
        # Process results with ENHANCED question extraction
        for result in results:
            # Get the embedded content
            embedded_content = result.get('embedded_content', result.get('main_content', ''))
            
            # Try enhanced extraction first (with LLM fallback)
            try:
                # Note: In individual scrapers, you won't have LLM access
                # So use the synchronous pattern-based extraction
                extracted_questions = extract_questions_from_content(embedded_content, max_questions=15)
                
                print(f"Extracted {len(extracted_questions)} questions from survey")
                
            except Exception as e:
                print(f"Question extraction failed: {e}")
                extracted_questions = []
            
            survey_data = {
                'survey_code': result.get('survey_code', 'Unknown'),
                'survey_date': result.get('survey_date', 'Unknown'),
                'survey_question': result.get('survey_question', ''),
                'url': result.get('url', ''),
                'embedded_content': embedded_content,
                'extracted_questions': extracted_questions
            }
            output_data['surveys'].append(survey_data)
        
        # Save to JSON file
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"Results saved to {args.output}")
        
    finally:
        scraper.cleanup()

if __name__ == "__main__":
    main()