#!/usr/bin/env python3
"""
Test script to verify ZenRows client works for Reddit subreddit scraping
"""

from zenrows import ZenRowsClient
from bs4 import BeautifulSoup
import json

def test_zenrows_reddit():
    """Test ZenRows client with Reddit communities page"""
    
    # Initialize ZenRows client
    client = ZenRowsClient("8a4c9ceb8b8017fff2e34c6aa292dc85ed504e52")
    
    # Target URL - Reddit best communities page 500
    url = "https://www.reddit.com/best/communities/500"
    
    # Parameters for premium proxy with US location
    params = {
        "premium_proxy": "true",
        "proxy_country": "us"
    }
    
    try:
        print(f"Fetching: {url}")
        print(f"Parameters: {params}")
        print("-" * 50)
        
        response = client.get(url, params=params)
        
        print(f"Status Code: {response.status_code}")
        print(f"Content Length: {len(response.text)} characters")
        print("-" * 50)
        
        # Print first 2000 characters to see if we got valid content
        print("First 2000 characters of response:")
        print(response.text[:2000])
        print("-" * 50)
        
        # Check if the response contains expected Reddit content
        if "reddit" in response.text.lower() and "communities" in response.text.lower():
            print("✅ Success: Response contains expected Reddit content")
        else:
            print("❌ Warning: Response may not contain expected Reddit content")
            
        return response.text
        
    except Exception as e:
        print(f"❌ Error occurred: {str(e)}")
        return None

def parse_subreddit_data(html_content):
    """Parse subreddit data from the HTML content"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Look for community divs with data-community-id attribute
    community_divs = soup.find_all('div', {'data-community-id': True})
    print(f"Found {len(community_divs)} community divs")
    
    subreddits = []
    
    for div in community_divs:
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
            
            subreddit_data = {
                'community_id': community_id,
                'name': prefixed_name,
                'url': subreddit_url,
                'subscribers_count': int(subscribers_count) if subscribers_count else 0,
                'displayed_count': displayed_count,
                'description': description,
                'icon_url': icon_url
            }
            
            subreddits.append(subreddit_data)
            print(f"Parsed: {prefixed_name} - {subscribers_count} members")
            
        except Exception as e:
            print(f"Error parsing community div: {e}")
            continue
    
    return subreddits

def test_full_scraping():
    """Test the complete scraping and parsing pipeline"""
    
    # Get the HTML content
    html_content = test_zenrows_reddit()
    
    if html_content:
        print("\n" + "="*60)
        print("PARSING SUBREDDIT DATA")
        print("="*60)
        
        # Parse the subreddit data
        subreddits = parse_subreddit_data(html_content)
        
        print(f"\n✅ Successfully parsed {len(subreddits)} subreddits")
        
        # Display first 5 subreddits as example
        print("\n📋 First 5 subreddits:")
        for i, sub in enumerate(subreddits[:5]):
            print(f"\n{i+1}. {sub['name']}")
            print(f"   Members: {sub['subscribers_count']} ({sub['displayed_count']})")
            print(f"   Description: {sub['description'][:100]}...")
            print(f"   URL: https://reddit.com{sub['url']}")
        
        # Save to JSON file for inspection
        with open('reddit_subreddits_500.json', 'w') as f:
            json.dump(subreddits, f, indent=2)
        print(f"\n💾 Saved all {len(subreddits)} subreddits to 'reddit_subreddits_500.json'")
        
        return subreddits
    else:
        print("❌ Failed to get HTML content")
        return None

if __name__ == "__main__":
    test_full_scraping()
