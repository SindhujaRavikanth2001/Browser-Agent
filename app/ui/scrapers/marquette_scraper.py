"""
Simple Marquette Law School Poll Scraper - UPDATED with Simple Question Extraction
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
        
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            print("✅ ChromeDriver loaded via webdriver-manager")
        except Exception as e:
            print(f"❌ webdriver-manager failed: {e}")
            try:
                service = Service('/usr/local/bin/chromedriver')
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                print("✅ ChromeDriver loaded from /usr/local/bin/chromedriver")
            except Exception as e2:
                try:
                    self.driver = webdriver.Chrome(options=chrome_options)
                    print("✅ ChromeDriver loaded automatically by Selenium")
                except Exception as e3:
                    print(f"❌ All ChromeDriver methods failed: {e3}")
                    raise e3
        
        self.driver.implicitly_wait(10)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    def extract_questions_marquette_simple(self, content):
        """Simple regex extraction for Marquette - looks for 'Question:' tags"""
        questions = []
        
        # Look for "Question:" followed by text
        question_pattern = r'Question:\s*(.+?)(?=\n|Question:|$)'
        matches = re.findall(question_pattern, content, re.IGNORECASE | re.DOTALL)
        
        for match in matches:
            question = match.strip()
            # Clean up the question
            question = re.sub(r'\s+', ' ', question)  # Remove extra whitespace
            question = question.replace('\n', ' ').strip()
            
            # Make sure it ends with a question mark
            if question and not question.endswith('?'):
                question += '?'
            
            if len(question) > 10 and len(question) < 500:  # Reasonable length
                questions.append(question)
        
        return questions
    
    def search_and_scrape(self, search_term, max_results=5):
        """Main scraping function"""
        self.results = []
        
        # Step 1: Navigate to search URL
        search_url = f"https://law.marquette.edu/poll/?s={search_term.replace(' ', '+')}"
        print(f"Step 1: Navigating to {search_url}")
        self.driver.get(search_url)
        time.sleep(5)
        
        # Step 2: Collect URLs of search results
        print("Step 2: Collecting URLs of search results...")
        urls = self.collect_urls(max_results)
        print(f"Found {len(urls)} URLs")
        
        # Step 3: Visit each URL and scrape content
        print("Step 3: Visiting each URL and scraping content...")
        for i, url in enumerate(urls[:max_results], 1):
            print(f"  Scraping {i}/{min(len(urls), max_results)}: {url}")
            
            try:
                self.driver.get(url)
                time.sleep(3)
                
                title = self.driver.title
                content = self.get_page_content()
                
                # SIMPLE question extraction for Marquette
                extracted_questions = self.extract_questions_marquette_simple(content)
                
                print(f"  Extracted {len(extracted_questions)} questions using simple regex")
                
                self.results.append({
                    'survey_code': f"MARQUETTE_{i}",
                    'survey_date': time.strftime('%Y-%m-%d'),
                    'survey_question': title,
                    'url': url,
                    'embedded_content': content,
                    'extracted_questions': extracted_questions
                })
                
                print(f"  ✓ Scraped: {title}")
            except Exception as e:
                print(f"  ❌ Error scraping {url}: {e}")
                continue
        
        print(f"Completed scraping {len(self.results)} results")
        return self.results
    
    def collect_urls(self, max_results=5):
        """Collect URLs from search results"""
        urls = []
        articles = self.driver.find_elements(By.CSS_SELECTOR, "article")
        
        for article in articles[:max_results]:
            try:
                link = article.find_element(By.CSS_SELECTOR, "h2 a")
                url = link.get_attribute('href')
                if url and 'law.marquette.edu/poll' in url and '?s=' not in url:
                    urls.append(url)
            except:
                continue
        
        return urls[:max_results]
    
    def get_page_content(self):
        """Get main content from current page"""
        try:
            content_element = self.driver.find_element(By.CSS_SELECTOR, ".entry-content")
            return content_element.text.strip()
        except:
            try:
                body = self.driver.find_element(By.TAG_NAME, "body")
                return body.text.strip()
            except:
                return "Could not extract content"
    
    def cleanup(self):
        """Close browser"""
        if self.driver:
            self.driver.quit()

def main():
    """Run the scraper with command line arguments"""
    parser = argparse.ArgumentParser(description='Marquette Poll scraper')
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
        
        for result in results:
            survey_data = {
                'survey_code': result.get('survey_code', 'Unknown'),
                'survey_date': result.get('survey_date', 'Unknown'),
                'survey_question': result.get('survey_question', ''),
                'url': result.get('url', ''),
                'embedded_content': result.get('embedded_content', ''),
                'extracted_questions': result.get('extracted_questions', [])
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