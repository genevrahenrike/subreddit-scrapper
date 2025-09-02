#!/usr/bin/env python3
"""
Test script to verify which ZenRows API keys are still valid
"""

from zenrows import ZenRowsClient
import time
import json
from datetime import datetime

# List of API keys to test
API_KEYS = [
    "7223275457c6a5ac015014a987d31845fe53e331",  # @ujaraksuzanne
    "eea61db54da490758519bf0f229cbfd6cf2e3f06",  # @svanhildurdemophon
    "cbf4f713a3a096dd3fb14c0ba0ee367a70ff9235",  # @tonosuman293
    "d66297a95435ed293207b38a7a377e985d585612",  # @trinitylivy
    "d57dda48129d37805f2009c7e89916410070777b",  # @shivstanislau
    "ac7849aedf31503f18d8645e91906845f44db67b",  # @shabnamruprecht
    "d9ec919fdb38f49ade0c7498806bd41afc8d8c45",  # @belram448
    "0c99cbca57e9a55c32175c890ce0f738181e9c7d",  # @karabosancha
    "98ec292605ef30bfc47ce992daa0ee593aede532",  # @ansgauretychis
    "567f093736d2120df2e2766df187fd4f28dd668f",  # @lastradawifi
    "1312dbdbc05be6c113502db85589e1893272f7d6",  # @shaditinatin
    "755c882d634ccdce249eb671341e9bd01f035b49",  # @lastradaxfinity
    "c62e5412af747ffb5408ff9a086f94356c7d199c",  # @belltacosp
    "062d3342a8f893c861c29e282b32383e5bf3b39d",  # @melodietex59
    "40e744b23a9c206e205c2f5d999f1a89f999165d",  # @edgarelena783
    "989d13df36e2843bf6db2d073a7d8f607f9ee866",  # @viviendagny
    "e186ec350881e1b848752f39cb67832dd94acfc2",  # @burrough1990
]

# User mapping for reference
USER_MAPPING = {
    "7223275457c6a5ac015014a987d31845fe53e331": "@ujaraksuzanne",
    "eea61db54da490758519bf0f229cbfd6cf2e3f06": "@svanhildurdemophon",
    "cbf4f713a3a096dd3fb14c0ba0ee367a70ff9235": "@tonosuman293",
    "d66297a95435ed293207b38a7a377e985d585612": "@trinitylivy",
    "d57dda48129d37805f2009c7e89916410070777b": "@shivstanislau",
    "ac7849aedf31503f18d8645e91906845f44db67b": "@shabnamruprecht",
    "d9ec919fdb38f49ade0c7498806bd41afc8d8c45": "@belram448",
    "0c99cbca57e9a55c32175c890ce0f738181e9c7d": "@karabosancha",
    "98ec292605ef30bfc47ce992daa0ee593aede532": "@ansgauretychis",
    "567f093736d2120df2e2766df187fd4f28dd668f": "@lastradawifi",
    "1312dbdbc05be6c113502db85589e1893272f7d6": "@shaditinatin",
    "755c882d634ccdce249eb671341e9bd01f035b49": "@lastradaxfinity",
    "c62e5412af747ffb5408ff9a086f94356c7d199c": "@belltacosp",
    "062d3342a8f893c861c29e282b32383e5bf3b39d": "@melodietex59",
    "40e744b23a9c206e205c2f5d999f1a89f999165d": "@edgarelena783",
    "989d13df36e2843bf6db2d073a7d8f607f9ee866": "@viviendagny",
    "e186ec350881e1b848752f39cb67832dd94acfc2": "@burrough1990",
}

def test_single_api_key(api_key, test_number, total_tests):
    """Test a single ZenRows API key"""
    
    print(f"\n{'='*60}")
    print(f"TEST {test_number}/{total_tests}: Testing API Key for {USER_MAPPING.get(api_key, 'Unknown User')}")
    print(f"Key: {api_key[:8]}...{api_key[-8:]}")
    print(f"{'='*60}")
    
    try:
        # Initialize ZenRows client
        client = ZenRowsClient(api_key)
        
        # Use a simple test URL (httpbin for testing)
        test_url = "https://httpbin.org/json"
        
        # Parameters for the request
        params = {
            "premium_proxy": "true",
            "proxy_country": "us"
        }
        
        print(f"Making test request to: {test_url}")
        
        # Make the request with a timeout
        response = client.get(test_url, params=params)
        
        print(f"Status Code: {response.status_code}")
        print(f"Content Length: {len(response.text)} characters")
        
        # Check if the response is successful
        if response.status_code == 200:
            print("✅ SUCCESS: API key is valid and working")
            try:
                # Try to parse JSON to ensure we got proper response
                json_response = response.json()
                print(f"Response preview: {str(json_response)[:200]}...")
                return {
                    "api_key": api_key,
                    "user": USER_MAPPING.get(api_key, "Unknown"),
                    "status": "valid",
                    "status_code": response.status_code,
                    "content_length": len(response.text),
                    "error": None,
                    "test_time": datetime.now().isoformat()
                }
            except:
                print("✅ SUCCESS: API key works but response may not be JSON")
                return {
                    "api_key": api_key,
                    "user": USER_MAPPING.get(api_key, "Unknown"),
                    "status": "valid",
                    "status_code": response.status_code,
                    "content_length": len(response.text),
                    "error": None,
                    "test_time": datetime.now().isoformat()
                }
        elif response.status_code == 401:
            print("❌ INVALID: API key is not authorized (401)")
            return {
                "api_key": api_key,
                "user": USER_MAPPING.get(api_key, "Unknown"),
                "status": "invalid",
                "status_code": response.status_code,
                "content_length": len(response.text),
                "error": "Unauthorized - API key invalid",
                "test_time": datetime.now().isoformat()
            }
        elif response.status_code == 402:
            print("❌ EXPIRED/QUOTA: API key has no credits or is expired (402)")
            return {
                "api_key": api_key,
                "user": USER_MAPPING.get(api_key, "Unknown"),
                "status": "expired_or_no_credits",
                "status_code": response.status_code,
                "content_length": len(response.text),
                "error": "Payment required - No credits or expired",
                "test_time": datetime.now().isoformat()
            }
        else:
            print(f"⚠️ UNEXPECTED: Unexpected status code {response.status_code}")
            print(f"Response content: {response.text[:500]}...")
            return {
                "api_key": api_key,
                "user": USER_MAPPING.get(api_key, "Unknown"),
                "status": "unexpected_response",
                "status_code": response.status_code,
                "content_length": len(response.text),
                "error": f"Unexpected status code: {response.status_code}",
                "test_time": datetime.now().isoformat()
            }
            
    except Exception as e:
        print(f"❌ ERROR: Exception occurred - {str(e)}")
        return {
            "api_key": api_key,
            "user": USER_MAPPING.get(api_key, "Unknown"),
            "status": "error",
            "status_code": None,
            "content_length": 0,
            "error": str(e),
            "test_time": datetime.now().isoformat()
        }

def test_all_api_keys():
    """Test all API keys and generate a report"""
    
    print("🚀 Starting ZenRows API Key Validation Test")
    print(f"Testing {len(API_KEYS)} API keys...")
    print(f"Test started at: {datetime.now().isoformat()}")
    
    results = []
    valid_keys = []
    invalid_keys = []
    expired_keys = []
    error_keys = []
    
    for i, api_key in enumerate(API_KEYS, 1):
        result = test_single_api_key(api_key, i, len(API_KEYS))
        results.append(result)
        
        # Categorize results
        if result["status"] == "valid":
            valid_keys.append(result)
        elif result["status"] == "invalid":
            invalid_keys.append(result)
        elif result["status"] == "expired_or_no_credits":
            expired_keys.append(result)
        else:
            error_keys.append(result)
        
        # Add a small delay between requests to be respectful
        if i < len(API_KEYS):
            print("⏳ Waiting 2 seconds before next test...")
            time.sleep(2)
    
    # Generate summary report
    print(f"\n{'='*80}")
    print("FINAL SUMMARY REPORT")
    print(f"{'='*80}")
    print(f"📊 Total API Keys Tested: {len(API_KEYS)}")
    print(f"✅ Valid & Working: {len(valid_keys)}")
    print(f"❌ Invalid/Unauthorized: {len(invalid_keys)}")
    print(f"💳 Expired/No Credits: {len(expired_keys)}")
    print(f"⚠️ Errors/Unexpected: {len(error_keys)}")
    
    # Show details for each category
    if valid_keys:
        print(f"\n✅ VALID KEYS ({len(valid_keys)}):")
        for key in valid_keys:
            print(f"   • {key['user']}: {key['api_key'][:8]}...{key['api_key'][-8:]}")
    
    if invalid_keys:
        print(f"\n❌ INVALID KEYS ({len(invalid_keys)}):")
        for key in invalid_keys:
            print(f"   • {key['user']}: {key['api_key'][:8]}...{key['api_key'][-8:]} - {key['error']}")
    
    if expired_keys:
        print(f"\n💳 EXPIRED/NO CREDITS ({len(expired_keys)}):")
        for key in expired_keys:
            print(f"   • {key['user']}: {key['api_key'][:8]}...{key['api_key'][-8:]} - {key['error']}")
    
    if error_keys:
        print(f"\n⚠️ ERRORS/UNEXPECTED ({len(error_keys)}):")
        for key in error_keys:
            print(f"   • {key['user']}: {key['api_key'][:8]}...{key['api_key'][-8:]} - {key['error']}")
    
    # Save detailed results to JSON file
    report_filename = f"zenrows_api_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    full_report = {
        "test_summary": {
            "total_tested": len(API_KEYS),
            "valid_count": len(valid_keys),
            "invalid_count": len(invalid_keys),
            "expired_count": len(expired_keys),
            "error_count": len(error_keys),
            "test_timestamp": datetime.now().isoformat()
        },
        "detailed_results": results,
        "valid_api_keys": [key["api_key"] for key in valid_keys],
        "recommended_keys": valid_keys[:3] if valid_keys else []  # Top 3 working keys
    }
    
    with open(report_filename, 'w') as f:
        json.dump(full_report, f, indent=2)
    
    print(f"\n💾 Detailed report saved to: {report_filename}")
    
    if valid_keys:
        print(f"\n🎉 Great! You have {len(valid_keys)} working API key(s)!")
        print("📝 You can use any of the valid keys listed above for your Reddit scraping project.")
    else:
        print("\n😞 Unfortunately, none of the tested API keys are currently valid.")
        print("💡 You may need to contact ZenRows support or get new API keys.")
    
    return full_report

if __name__ == "__main__":
    test_all_api_keys()
