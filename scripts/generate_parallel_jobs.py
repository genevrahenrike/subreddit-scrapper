#!/usr/bin/env python3
"""
Generate commands to split subreddit scraping across multiple servers/IPs.
"""

import argparse

def generate_jobs(total_subs, num_servers, concurrency_per_server=4):
    """Generate job commands for parallel execution across servers."""
    
    subs_per_server = total_subs // num_servers
    remainder = total_subs % num_servers
    
    commands = []
    start_idx = 0
    
    for i in range(num_servers):
        # Distribute remainder across first few servers
        limit = subs_per_server + (1 if i < remainder else 0)
        
        cmd = f"""# Server {i+1}
PROXY_SERVER="http://proxy{i+1}:port" CONCURRENCY={concurrency_per_server} OVERWRITE=1 \\
./scripts/run_frontpage_batch.sh --start {start_idx} --limit {limit}"""
        
        commands.append(cmd)
        print(f"Server {i+1:2d}: Range [{start_idx:6d}, {start_idx + limit:6d}) = {limit:5d} subreddits")
        start_idx += limit
    
    print(f"\nTotal coverage: {start_idx:,} subreddits")
    print(f"Total processes: {num_servers * concurrency_per_server}")
    print("\n" + "="*80)
    print("COMMANDS TO RUN:")
    print("="*80)
    
    for cmd in commands:
        print(cmd)
        print()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=332832, help="Total number of subreddits")
    parser.add_argument("--servers", type=int, default=6, help="Number of servers/IPs")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrency per server")
    
    args = parser.parse_args()
    generate_jobs(args.total, args.servers, args.concurrency)
