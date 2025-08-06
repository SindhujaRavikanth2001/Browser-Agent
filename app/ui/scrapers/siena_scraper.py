"""
Siena Research Institute Scraper - FIXED
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
import argparse
import json
import re

class SienaResearchScraper:
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
            from webdriver_manager.chrome import ChromeDriverManager
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
        
    def search_and_scrape(self, keyword, max_results=5):
        """Main scraping function"""
        try:
            search_url = f"https://sri.siena.edu/?s={keyword.replace(' ', '+')}"
            print(f"Navigating to: {search_url}")
            
            self.driver.get(search_url)
            time.sleep(5)
            
            print("Waiting for search results to load...")
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".search-results, .post, article, .entry"))
                )
                print("Search results page loaded")
                time.sleep(2)
            except:
                print("Warning: Could not detect search results elements")
            
            result_links = self.find_result_links()
            
            if not result_links:
                print("No search result links found!")
                return
            
            print(f"Found {len(result_links)} search result links")
            
            links_to_process = result_links[:max_results]
            
            for i, link_info in enumerate(links_to_process, 1):
                try:
                    print(f"\n--- Processing result {i}/{len(links_to_process)} ---")
                    print(f"Title: {link_info['title']}")
                    print(f"URL: {link_info['url']}")
                    
                    self.driver.get(link_info['url'])
                    time.sleep(3)
                    
                    content = self.scrape_page_content(link_info)
                    
                    # Add survey metadata
                    content['survey_code'] = f"SIENA_{i}"
                    content['survey_date'] = time.strftime('%Y-%m-%d')
                    content['survey_question'] = content.get('original_title', 'Unknown')
                    
                    # NO question extraction here - will be done by LLM in main app
                    
                    self.results.append(content)
                    
                    print(f"✓ Result {i} scraped successfully")
                    time.sleep(2)
                    
                except Exception as e:
                    print(f"✗ Error processing result {i}: {e}")
                    continue
            
            print(f"\nScraping completed! Successfully processed {len(self.results)} results.")
            
        except Exception as e:
            print(f"Error in main scraping: {e}")
    
    def find_result_links(self):
        """Find all search result links on the page"""
        try:
            result_links = []
            
            link_selectors = [
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
            
            if not result_links:
                print("No specific search results found, trying general links...")
                try:
                    all_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'sri.siena.edu')]")
                    
                    for link in all_links[:15]:
                        href = link.get_attribute('href')
                        title = link.text.strip()
                        
                        if (href and title and len(title) > 5
                            and not href.endswith(('.pdf', '.jpg', '.png'))):
                            
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
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            page_title = self.driver.title
            
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
            
            if not main_content:
                try:
                    body = self.driver.find_element(By.TAG_NAME, "body")
                    main_content = body.text.strip()
                except:
                    main_content = "Could not extract content"
            
            tables_content = ""
            try:
                tables = self.driver.find_elements(By.TAG_NAME, "table")
                for table in tables:
                    table_text = table.text.strip()
                    if len(table_text) > 50:
                        tables_content += f"\n--- TABLE DATA ---\n{table_text}\n"
            except:
                pass
            
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
                'main_content': main_content[:8000],
                'embedded_content': main_content[:8000],  # Same as main_content for consistency
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
                'embedded_content': f'Error scraping content: {str(e)}',
                'tables_content': '',
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
    
    def cleanup(self):
        """Close browser"""
        if self.driver:
            self.driver.quit()
            print("Browser closed")

def main():
    """Run the scraper with command line arguments"""
    parser = argparse.ArgumentParser(description='Siena Poll scraper')
    parser.add_argument('--keyword', required=True, help='Search keyword')
    parser.add_argument('--max-results', type=int, default=5, help='Maximum results to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--headless', default='true', help='Run in headless mode')
    
    args = parser.parse_args()
    headless = args.headless.lower() == 'true'
    
    scraper = SienaResearchScraper(headless=headless)
    
    try:
        scraper.search_and_scrape(args.keyword, args.max_results)
        
        # Convert results to the expected format and save as JSON
        output_data = {
            'keyword': args.keyword,
            'max_results': args.max_results,
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'surveys': []
        }
        
        # Process results WITHOUT question extraction (LLM will handle this)
        for result in scraper.results:
            survey_data = {
                'survey_code': result.get('survey_code', 'Unknown'),
                'survey_date': result.get('survey_date', 'Unknown'),
                'survey_question': result.get('survey_question', ''),
                'url': result.get('url', ''),
                'embedded_content': result.get('embedded_content', ''),
                # NO extracted_questions field - LLM will handle this
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