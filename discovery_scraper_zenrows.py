#!/usr/bin/env python3
"""
Complete Reddit Communities Scraper
Scrapes subreddit ranking pages from 1 to 1000 using ZenRows
"""

import time
import json
import os
from datetime import datetime
from zenrows import ZenRowsClient
from bs4 import BeautifulSoup

class RedditCommunitiesScraper:
    def __init__(self, api_key):
        """Initialize the scraper with ZenRows API key"""
        self.client = ZenRowsClient(api_key)
        self.base_url = "https://www.reddit.com/best/communities/"
        self.params = {
            "premium_proxy": "true",
            "proxy_country": "us"
        }
        self.all_subreddits = []
        
    def scrape_page(self, page_number, delay=2):
        """Scrape a single communities page"""
        url = f"{self.base_url}{page_number}"
        
        print(f"📄 Scraping page {page_number}: {url}")
        
        try:
            response = self.client.get(url, params=self.params)
            
            if response.status_code != 200:
                print(f"❌ Error: Got status code {response.status_code} for page {page_number}")
                return []
            
            # Parse the HTML content
            subreddits = self.parse_subreddit_data(response.text, page_number)
            
            print(f"✅ Found {len(subreddits)} subreddits on page {page_number}")
            
            # Add delay to be respectful to the service
            if delay > 0:
                time.sleep(delay)
                
            return subreddits
            
        except Exception as e:
            print(f"❌ Error scraping page {page_number}: {str(e)}")
            return []
    
    def parse_subreddit_data(self, html_content, page_number):
        """Parse subreddit data from the HTML content"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Look for community divs with data-community-id attribute
        community_divs = soup.find_all('div', {'data-community-id': True})
        
        subreddits = []
        
        for i, div in enumerate(community_divs):
            try:
                # Extract data from attributes
                community_id = div.get('data-community-id')
                prefixed_name = div.get('data-prefixed-name')
                subscribers_count = div.get('data-subscribers-count')
                description = div.get('data-public-description-text', '')
                icon_url = div.get('data-icon-url', '')
                
                # Extract the displayed member count from the h6 element
                member_count_elem = div.find('h6', class_='flex flex-col font-bold justify-center items-center text-12 w-2xl m-0 truncate')
                displayed_count = member_count_elem.text.strip() if member_count_elem else ''
                
                # Extract subreddit link
                link_elem = div.find('a', href=True)
                subreddit_url = link_elem.get('href') if link_elem else ''
                
                # Calculate approximate rank (assuming ~50 per page, but pages may vary)
                approximate_rank = ((page_number - 1) * 50) + i + 1
                
                subreddit_data = {
                    'rank': approximate_rank,
                    'page': page_number,
                    'community_id': community_id,
                    'name': prefixed_name,
                    'url': subreddit_url,
                    'full_url': f"https://reddit.com{subreddit_url}" if subreddit_url else '',
                    'subscribers_count': int(subscribers_count) if subscribers_count else 0,
                    'displayed_count': displayed_count,
                    'description': description,
                    'icon_url': icon_url,
                    'scraped_at': datetime.now().isoformat()
                }
                
                subreddits.append(subreddit_data)
                
            except Exception as e:
                print(f"⚠️  Error parsing community div on page {page_number}: {e}")
                continue
        
        return subreddits
    
    def scrape_all_pages(self, start_page=1, end_page=1000, delay=2, save_every=10):
        """Scrape all pages from start_page to end_page"""
        
        print(f"🚀 Starting to scrape Reddit communities from page {start_page} to {end_page}")
        print(f"⏱️  Delay between requests: {delay} seconds")
        print(f"💾 Saving progress every {save_every} pages")
        print("="*60)
        
        start_time = datetime.now()
        
        for page in range(start_page, end_page + 1):
            subreddits = self.scrape_page(page, delay)
            self.all_subreddits.extend(subreddits)
            
            # Save progress every N pages
            if page % save_every == 0:
                self.save_data(f"reddit_communities_progress_page_{page}.json")
                print(f"💾 Saved progress: {len(self.all_subreddits)} total subreddits so far")
            
            # Print progress
            if page % 5 == 0:
                elapsed = datetime.now() - start_time
                print(f"⏱️  Progress: {page}/{end_page} pages ({len(self.all_subreddits)} subreddits) - Elapsed: {elapsed}")
        
        # Final save
        self.save_data("reddit_communities_complete.json")
        
        total_time = datetime.now() - start_time
        print("\n" + "="*60)
        print(f"🎉 Scraping complete!")
        print(f"📊 Total subreddits scraped: {len(self.all_subreddits)}")
        print(f"⏱️  Total time: {total_time}")
        print(f"💾 Data saved to: reddit_communities_complete.json")
        
        return self.all_subreddits
    
    def save_data(self, filename):
        """Save scraped data to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.all_subreddits, f, indent=2, ensure_ascii=False)
    
    def load_data(self, filename):
        """Load previously scraped data from JSON file"""
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                self.all_subreddits = json.load(f)
            print(f"📂 Loaded {len(self.all_subreddits)} subreddits from {filename}")
            return True
        return False
    
    def get_statistics(self):
        """Get statistics about the scraped data"""
        if not self.all_subreddits:
            print("No data available")
            return
        
        print("\n📊 SCRAPING STATISTICS")
        print("="*40)
        print(f"Total subreddits: {len(self.all_subreddits)}")
        
        # Count by subscriber ranges
        ranges = {
            "1M+": 0,
            "100K-1M": 0,
            "10K-100K": 0,
            "1K-10K": 0,
            "<1K": 0
        }
        
        for sub in self.all_subreddits:
            count = sub['subscribers_count']
            if count >= 1000000:
                ranges["1M+"] += 1
            elif count >= 100000:
                ranges["100K-1M"] += 1
            elif count >= 10000:
                ranges["10K-100K"] += 1
            elif count >= 1000:
                ranges["1K-10K"] += 1
            else:
                ranges["<1K"] += 1
        
        print("\nSubscriber count ranges:")
        for range_name, count in ranges.items():
            print(f"  {range_name}: {count} subreddits")
        
        # Top 10 by subscribers
        top_10 = sorted(self.all_subreddits, key=lambda x: x['subscribers_count'], reverse=True)[:10]
        print(f"\nTop 10 by subscribers:")
        for i, sub in enumerate(top_10, 1):
            print(f"  {i:2d}. {sub['name']} - {sub['subscribers_count']:,} members")


def main():
    """Main function to run the scraper"""
    
    # Initialize scraper with your ZenRows API key
    api_key = "8a4c9ceb8b8017fff2e34c6aa292dc85ed504e52"
    scraper = RedditCommunitiesScraper(api_key)
    
    # Test with a small range first (pages 1-5)
    print("🧪 Testing with pages 1-5 first...")
    test_subreddits = scraper.scrape_all_pages(start_page=1, end_page=5, delay=1, save_every=2)
    
    if test_subreddits:
        print("\n✅ Test successful! Here's what we got:")
        scraper.get_statistics()
        
        # Ask user if they want to continue with full scraping
        response = input("\nContinue with full scraping (pages 1-1000)? This will take ~30-45 minutes. (y/n): ")
        
        if response.lower() == 'y':
            # Reset for full scraping
            scraper.all_subreddits = []
            scraper.scrape_all_pages(start_page=1, end_page=1000, delay=2, save_every=25)
            scraper.get_statistics()
        else:
            print("Test data saved. You can run full scraping later.")
    else:
        print("❌ Test failed. Please check your setup.")


if __name__ == "__main__":
    main()

from zenrows import ZenRowsClient
from bs4 import BeautifulSoup
import json
import re
import time
from typing import List, Dict, Optional

class RedditCommunitiesScraper:
    def __init__(self, api_key: str):
        """Initialize the scraper with ZenRows API key"""
        self.client = ZenRowsClient(api_key)
        self.base_url = "https://www.reddit.com/best/communities"
        
    def get_page(self, page_num: int) -> Optional[str]:
        """Fetch a specific communities page"""
        url = f"{self.base_url}/{page_num}"
        params = {
            "premium_proxy": "true",
            "proxy_country": "us"
        }
        
        try:
            print(f"Fetching page {page_num}...")
            response = self.client.get(url, params=params)
            
            if response.status_code == 200:
                print(f"✅ Successfully fetched page {page_num}")
                return response.text
            else:
                print(f"❌ Failed to fetch page {page_num}: Status {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Error fetching page {page_num}: {str(e)}")
            return None
    
    def parse_communities_data(self, html_content: str) -> List[Dict]:
        """Parse subreddit data from HTML content"""
        soup = BeautifulSoup(html_content, 'html.parser')
        communities = []
        
        # Look for script tags containing JSON data
        script_tags = soup.find_all('script')
        
        for script in script_tags:
            if script.string and 'window.__PRELOADED_STATE__' in script.string:
                # Extract the JSON data
                script_content = script.string
                
                # Find the JSON part
                json_start = script_content.find('{')
                json_end = script_content.rfind('}') + 1
                
                if json_start != -1 and json_end != -1:
                    try:
                        json_str = script_content[json_start:json_end]
                        data = json.loads(json_str)
                        
                        # Navigate through the data structure to find communities
                        communities = self._extract_communities_from_data(data)
                        break
                        
                    except json.JSONDecodeError as e:
                        print(f"JSON parsing error: {e}")
                        continue
        
        # If JSON parsing fails, try HTML parsing as fallback
        if not communities:
            communities = self._parse_html_fallback(soup)
            
        return communities
    
    def _extract_communities_from_data(self, data: Dict) -> List[Dict]:
        """Extract community data from the parsed JSON"""
        communities = []
        
        # Look for communities in various possible locations in the data structure
        def find_communities_recursive(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == 'communities' and isinstance(value, list):
                        return value
                    elif key == 'data' and isinstance(value, dict):
                        result = find_communities_recursive(value, f"{path}.{key}")
                        if result:
                            return result
                    elif isinstance(value, (dict, list)):
                        result = find_communities_recursive(value, f"{path}.{key}")
                        if result:
                            return result
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    result = find_communities_recursive(item, f"{path}[{i}]")
                    if result:
                        return result
            return None
        
        raw_communities = find_communities_recursive(data)
        
        if raw_communities:
            for community in raw_communities:
                if isinstance(community, dict):
                    parsed_community = self._parse_community_data(community)
                    if parsed_community:
                        communities.append(parsed_community)
        
        return communities
    
    def _parse_community_data(self, community_data: Dict) -> Optional[Dict]:
        """Parse individual community data"""
        try:
            community = {
                'name': community_data.get('name', ''),
                'display_name': community_data.get('displayName', ''),
                'title': community_data.get('title', ''),
                'description': community_data.get('description', ''),
                'subscribers': community_data.get('subscribers', 0),
                'members': community_data.get('members', 0),
                'url': community_data.get('url', ''),
                'icon_url': community_data.get('iconUrl', ''),
                'banner_url': community_data.get('bannerUrl', ''),
                'created_utc': community_data.get('createdUtc', 0),
                'over18': community_data.get('over18', False),
                'rank': community_data.get('rank', 0)
            }
            
            # Clean up the data
            if community['name'] and not community['name'].startswith('r/'):
                community['name'] = f"r/{community['name']}"
                
            return community
            
        except Exception as e:
            print(f"Error parsing community data: {e}")
            return None
    
    def _parse_html_fallback(self, soup: BeautifulSoup) -> List[Dict]:
        """Fallback HTML parsing if JSON parsing fails"""
        communities = []
        
        # Look for common patterns in Reddit's HTML structure
        # This is a fallback method and may need adjustment based on actual HTML structure
        
        # Try to find community elements by various selectors
        selectors = [
            '[data-testid*="community"]',
            '.community-item',
            '[class*="community"]',
            '[class*="subreddit"]'
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                print(f"Found {len(elements)} elements with selector: {selector}")
                break
        
        return communities

def test_parser():
    """Test the parser with a sample page"""
    scraper = RedditCommunitiesScraper("8a4c9ceb8b8017fff2e34c6aa292dc85ed504e52")
    
    # Test with page 500
    html_content = scraper.get_page(500)
    
    if html_content:
        # Save the raw HTML for inspection
        with open('reddit_page_500.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
        print("✅ Saved raw HTML to reddit_page_500.html")
        
        # Parse the communities
        communities = scraper.parse_communities_data(html_content)
        
        print(f"Found {len(communities)} communities")
        
        if communities:
            print("\nFirst few communities:")
            for i, community in enumerate(communities[:3]):
                print(f"{i+1}. {community}")
        else:
            print("No communities found. Let's analyze the HTML structure...")
            
            # Let's look at the HTML structure to understand how to parse it
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Check for script tags with data
            scripts = soup.find_all('script')
            print(f"Found {len(scripts)} script tags")
            
            for i, script in enumerate(scripts[:5]):  # Check first 5 scripts
                if script.string and len(script.string) > 100:
                    content = script.string[:200] + "..." if len(script.string) > 200 else script.string
                    print(f"Script {i+1}: {content}")
    
if __name__ == "__main__":
    # Install required package first
    import subprocess
    import sys
    
    try:
        import bs4
    except ImportError:
        print("Installing BeautifulSoup4...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4"])
        import bs4
    
    test_parser()
