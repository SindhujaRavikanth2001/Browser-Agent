"""
Simple Marquette Law School Poll Scraper
Step 1: Navigate to search URL
Step 2: Collect URLs of 8 search results  
Step 3: Visit each URL and scrape content
Step 4: Store everything in txt file
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
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

class SimpleMarquetteScraper:
    def __init__(self, headless=True):
        self.driver = None
        self.setup_driver(headless)
    
    def setup_driver(self, headless=True):
        """Initialize Chrome driver"""
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.implicitly_wait(10)
    
    def scrape(self, search_term):
        """Main scraping function"""
        results = []
        
        # Step 1: Navigate to search URL
        search_url = f"https://law.marquette.edu/poll/?s={search_term.replace(' ', '+')}"
        print(f"Step 1: Navigating to {search_url}")
        self.driver.get(search_url)
        time.sleep(5)
        
        # Step 2: Collect URLs of 8 search results
        print("Step 2: Collecting URLs of 8 search results...")
        urls = self.collect_urls()
        print(f"Found {len(urls)} URLs: {urls}")
        
        # Step 3: Visit each URL and scrape content
        print("Step 3: Visiting each URL and scraping content...")
        for i, url in enumerate(urls, 1):
            print(f"  Scraping {i}/{len(urls)}: {url}")
            
            self.driver.get(url)
            time.sleep(3)
            
            # Get page title
            title = self.driver.title
            
            # Get main content
            content = self.get_page_content()
            
            results.append({
                'number': i,
                'url': url,
                'title': title,
                'content': content
            })
            
            print(f"  ✓ Scraped: {title}")
        
        # Step 4: Store everything in txt file
        print("Step 4: Storing everything in txt file...")
        self.save_results_json(search_term, results)
        print("Done!")
        
        return results
    
    def collect_urls(self):
        """Collect URLs from search results"""
        urls = []
        
        # Find all article links
        articles = self.driver.find_elements(By.CSS_SELECTOR, "article")
        
        for article in articles[:8]:  # Get first 8
            try:
                link = article.find_element(By.CSS_SELECTOR, "h2 a")
                url = link.get_attribute('href')
                if url and 'law.marquette.edu/poll' in url and '?s=' not in url:
                    urls.append(url)
            except:
                continue
        
        return urls[:8]  # Ensure we only get 8
    
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

def main():
    """Run the scraper with command line arguments"""
    parser = argparse.ArgumentParser(description='Poll scraper')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=10, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    headless = args.headless.lower() == 'true'
    
    scraper = SimpleMarquetteScraper(headless=headless)  # Replace with actual class name
    
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