"""
Polling site scrapers for research question extraction
"""

from .marist_scraper import IframeMaristScraper
from .siena_scraper import SienaResearchScraper  
from .quinnipiac_scraper import QuinnipiacPollScraper
from .marquette_scraper import SimpleMarquetteScraper

__all__ = [
    'IframeMaristScraper',
    'SienaResearchScraper', 
    'QuinnipiacPollScraper',
    'SimpleMarquetteScraper'
]