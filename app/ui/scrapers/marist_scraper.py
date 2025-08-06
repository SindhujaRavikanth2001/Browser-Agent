"""
Iframe Marist Poll Scraper - Handles the embedded iframe with search results
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
import argparse
import json
import re

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

class IframeMaristScraper:
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
            from webdriver_manager.chrome import ChromeDriverManager
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
                    # Method 4: Try system chromedriver
                    try:
                        service = Service('chromedriver')  # Assumes chromedriver is in PATH
                        self.driver = webdriver.Chrome(service=service, options=chrome_options)
                        print("✅ ChromeDriver loaded from system PATH")
                    except Exception as e4:
                        print(f"❌ System ChromeDriver failed: {e4}")
                        raise e3
        
        # Set implicit wait and other configurations
        self.driver.implicitly_wait(10)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
    def search_and_scrape(self, keyword, max_results=5):
        """Main scraping function"""
        try:
            # Step 1: Navigate to search results
            search_url = f"https://maristpoll.marist.edu/search-survey-questions/?keyword={keyword.replace(' ', '+')}"
            print(f"Navigating to: {search_url}")
            
            self.driver.get(search_url)
            time.sleep(5)  # Wait for page to load
            
            # Step 2: Wait for iframe to load
            print("Waiting for iframe to load...")
            try:
                iframe = WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.TAG_NAME, "iframe"))
                )
                print("Iframe found")
                time.sleep(3)
            except:
                print("No iframe found!")
                return
            
            # Step 3: Switch to iframe
            print("Switching to iframe...")
            self.driver.switch_to.frame(iframe)
            time.sleep(3)
            
            # Step 4: Wait for search results in iframe
            print("Waiting for search results in iframe...")
            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.XPATH, "//table//tr[position()>1]"))
                )
                print("Search results loaded in iframe")
                time.sleep(2)
            except:
                print("Warning: Could not detect search results in iframe")
            
            # Step 5: Find HTML Preview buttons in iframe
            html_preview_buttons = self.driver.find_elements(By.XPATH, 
                "//button[contains(text(), 'HTML Preview') or contains(@ng-click, 'showHTMLPreview')]")
            
            print(f"Found {len(html_preview_buttons)} HTML Preview buttons in iframe")
            
            if len(html_preview_buttons) == 0:
                # Try alternative selectors for buttons in iframe
                alt_selectors = [
                    "//button[contains(text(), 'Preview')]",
                    "//*[contains(text(), 'HTML Preview')]",
                    "//button[contains(@class, 'btn') and contains(text(), 'HTML')]",
                    "//button[contains(@title, 'HTML')]"
                ]
                
                for selector in alt_selectors:
                    buttons = self.driver.find_elements(By.XPATH, selector)
                    if buttons:
                        html_preview_buttons = buttons
                        print(f"Found {len(buttons)} buttons with alternative selector in iframe")
                        break
            
            if len(html_preview_buttons) == 0:
                print("No HTML Preview buttons found in iframe!")
                # Take screenshot for debugging
                self.driver.save_screenshot("iframe_debug.png")
                # Switch back to main frame before returning
                self.driver.switch_to.default_content()
                return
            
            # Step 6: Process each HTML Preview button
            buttons_to_process = html_preview_buttons[:max_results]
            
            for i, button in enumerate(buttons_to_process, 1):
                try:
                    print(f"Processing result {i}/{len(buttons_to_process)}")
                    
                    # Extract survey info from the row
                    survey_code, survey_date, survey_question = self.extract_survey_info(button)
                    print(f"Survey: {survey_code}")
                    
                    # Scroll to button and click
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", button)
                    time.sleep(1)
                    
                    button.click()
                    print("HTML Preview button clicked - content should now be visible")
                    
                    # Wait for the embedded content to load
                    time.sleep(3)
                    
                    # Scrape the embedded HTML content
                    content = self.scrape_embedded_content(survey_code, survey_date, survey_question)
                    
                    self.results.append(content)
                    
                    # IMPORTANT: Click the HTML Preview button again to toggle it off
                    # This prevents content from previous rows interfering with next rows
                    print("Clicking HTML Preview button again to toggle off...")
                    try:
                        # Method 1: Try regular click
                        button.click()
                        print("HTML Preview toggled off with regular click")
                    except:
                        try:
                            # Method 2: Try JavaScript click if regular click fails
                            self.driver.execute_script("arguments[0].click();", button)
                            print("HTML Preview toggled off with JavaScript click")
                        except:
                            try:
                                # Method 3: Scroll to button first, then click
                                self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
                                time.sleep(1)
                                button.click()
                                print("HTML Preview toggled off after scrolling")
                            except:
                                print("Warning: Could not toggle off HTML Preview - continuing anyway")
                    
                    time.sleep(1)
                    print("Ready for next result")
                    
                    # Small delay between requests
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Error processing result {i}: {e}")
                    # Try to toggle off the button if there was an error
                    try:
                        # Try multiple methods to toggle off
                        try:
                            button.click()
                        except:
                            try:
                                self.driver.execute_script("arguments[0].click();", button)
                            except:
                                pass
                        print("Attempted to toggle off HTML Preview after error")
                    except:
                        print("Could not toggle off after error")
                    continue
            
            # Step 7: Switch back to main frame
            self.driver.switch_to.default_content()
            
            # Step 8: Save results
            print(f"Scraping completed! Processed {len(self.results)} results.")
            
        except Exception as e:
            print(f"Error in main scraping: {e}")
            # Make sure we're back to main frame
            self.driver.switch_to.default_content()
    
    def extract_survey_info(self, button):
        """Extract survey information from the table row in iframe"""
        try:
            # Find the parent row
            row = button.find_element(By.XPATH, "./ancestor::tr")
            
            survey_code = "Unknown"
            survey_date = "Unknown"
            survey_question = "Unknown"
            
            # Get all cells in the row
            cells = row.find_elements(By.TAG_NAME, "td")
            
            for cell in cells:
                cell_text = cell.text.strip()
                
                # Look for survey code (contains year and letters)
                if any(year in cell_text for year in ["2025", "2024", "2023"]) and len(cell_text) < 50:
                    survey_code = cell_text
                
                # Look for dates (contains slashes)
                elif "/" in cell_text and len(cell_text) < 30:
                    survey_date = cell_text
                
                # Look for question text (longer text with question words)
                elif len(cell_text) > 30 and any(word in cell_text.lower() for word in ["do you", "what", "how", "which", "should"]):
                    survey_question = cell_text[:300]  # Limit length
            
            return survey_code, survey_date, survey_question
            
        except Exception as e:
            print(f"Error extracting survey info: {e}")
            return "Unknown", "Unknown", "Unknown"
    
    def scrape_embedded_content(self, survey_code, survey_date, survey_question):
        """Scrape the embedded HTML preview content from iframe"""
        try:
            # Look for the embedded HTML content area in iframe
            content_selectors = [
                ".fullview-html",
                ".html-preview-box", 
                "[ng-show*='preview-html']",
                ".parc-content",
                ".tab-content",
                "table.table-bordered",
                "table.table-striped",
                ".table"
            ]
            
            embedded_content = ""
            table_data = ""
            
            # Try to find the embedded content
            for selector in content_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_displayed() and len(element.text.strip()) > 50:
                            text = element.text.strip()
                            if len(text) > len(embedded_content):
                                embedded_content = text
                except:
                    continue
            
            # Look specifically for tables with survey data
            try:
                tables = self.driver.find_elements(By.XPATH, 
                    "//table[contains(@class, 'table') or contains(@class, 'preview') or contains(@class, 'parc')]")
                
                for table in tables:
                    if table.is_displayed():
                        table_text = table.text.strip()
                        # Check if table contains percentage data
                        if "%" in table_text and len(table_text) > 50:
                            table_data += f"\n--- TABLE DATA ---\n{table_text}\n"
                            
            except Exception as e:
                print(f"Error extracting table data: {e}")
            
            # If no specific content found, get any visible content from the current view
            if not embedded_content and not table_data:
                try:
                    # Look for any new content that appeared after clicking
                    body = self.driver.find_element(By.TAG_NAME, "body")
                    embedded_content = body.text.strip()[:2000]  # Get some content
                except:
                    embedded_content = "No content found"
            
            return {
                'survey_code': survey_code,
                'survey_date': survey_date,
                'survey_question': survey_question,
                'embedded_content': embedded_content[:4000],  # Limit length
                'table_data': table_data[:3000],  # Limit length
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            print(f"Error scraping embedded content: {e}")
            return {
                'survey_code': survey_code,
                'survey_date': survey_date,
                'survey_question': survey_question,
                'embedded_content': f'Error scraping: {str(e)}',
                'table_data': '',
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
    
    def cleanup(self):
        """Close browser"""
        if self.driver:
            self.driver.quit()
            print("Browser closed")

def main():
    """Run the scraper with command line arguments"""
    parser = argparse.ArgumentParser(description='Marist Poll scraper')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=5, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    headless = args.headless.lower() == 'true'
    
    scraper = IframeMaristScraper(headless=headless)
    
    try:
        scraper.search_and_scrape(args.keyword, args.max_results)
        
        # Convert results to the expected format and save as JSON
        output_data = {
            'keyword': args.keyword,
            'max_results': args.max_results,
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'surveys': []
        }
        
        # Process results WITHOUT question extraction
        for result in scraper.results:
            survey_data = {
                'survey_code': result.get('survey_code', 'Unknown'),
                'survey_date': result.get('survey_date', 'Unknown'),
                'survey_question': result.get('survey_question', ''),
                'url': result.get('url', ''),
                'embedded_content': result.get('embedded_content', ''),
                # NO extracted_questions - LLM will handle this
            }
            output_data['surveys'].append(survey_data)
        
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"Results saved to {args.output}")
        
    finally:
        scraper.cleanup()

# Use the enhanced question extraction from the shared module
# The extract_questions_from_content function is now imported from question_extractor

if __name__ == "__main__":
    main()