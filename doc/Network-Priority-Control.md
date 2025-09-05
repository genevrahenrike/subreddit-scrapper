# Network Priority Control for Reddit Scraper

This document explains how to run the Reddit scraper with lower network and CPU priority to avoid competing with important user traffic.

## Quick Start

### Method 1: Built-in Low Priority Flag
```bash
# Run with low priority
python subreddit_frontpage_scraper.py --subs r/technology --low-priority

# Custom nice level (higher = lower priority)
python subreddit_frontpage_scraper.py --subs r/technology --low-priority --nice-level 15
```

### Method 2: Shell Wrapper (Recommended)
```bash
# Basic low priority run
./run_low_priority.sh -- --subs r/technology r/programming

# With bandwidth limiting (requires trickle)
./run_low_priority.sh -b 500k -- --subs r/technology --min-posts 30

# Custom nice level
./run_low_priority.sh -n 15 -- --subs r/technology --disable-images
```

## How It Works

### CPU Priority (Process Nice Level)
- Uses Unix `nice` command to lower CPU scheduling priority
- Nice levels: 0 (normal) to 19 (lowest priority)
- Default low priority level: 10
- Higher numbers = lower priority = less CPU competition

### I/O Priority (Linux only)
- Automatically attempts to set I/O priority to "idle" class using `ionice`
- On macOS, this feature is not available but the script continues normally
- Reduces disk I/O competition with user applications

### Network Bandwidth Limiting (Optional)
- Uses `trickle` utility for bandwidth throttling
- Install: `brew install trickle` (macOS) or `apt-get install trickle` (Linux)
- Limits both download and upload bandwidth
- Does NOT slow down the scraper, just prevents it from saturating the connection

## Installation Requirements

### Basic (CPU Priority only)
No additional installation needed - uses built-in Unix `nice` command.

### Advanced (Network Bandwidth Control)
```bash
# macOS
brew install trickle

# Ubuntu/Debian
sudo apt-get install trickle

# CentOS/RHEL
sudo yum install trickle
```

## Usage Examples

### Background Processing During Work Hours
```bash
# Low priority with bandwidth limit during business hours
./run_low_priority.sh -n 15 -b 300k -- --subs r/technology r/programming r/webdev

# Very low priority for overnight runs
./run_low_priority.sh -n 19 -b 1m -- --file large_subreddit_list.txt
```

### Development Testing
```bash
# Low priority development testing
./run_low_priority.sh -- --subs r/test --headless --min-posts 5 --overwrite
```

### Batch Processing
```bash
# Large batch with minimal system impact
./run_low_priority.sh -n 15 -b 500k -- \
  --file subreddit_list.txt \
  --disable-images \
  --min-posts 25 \
  --multi-profile
```

## Configuration Options

### Built-in Options
- `--low-priority`: Enable low priority mode
- `--nice-level N`: Set nice level (0-19, default: 10)

### Shell Wrapper Options
- `-n, --nice LEVEL`: Set nice level (0-19, default: 10)
- `-b, --bandwidth LIMIT`: Bandwidth limit (e.g., 500k, 1m)
- `-t, --use-trickle`: Force use of trickle
- `-h, --help`: Show help

## Bandwidth Limit Formats
- `500k` = 500 KB/s
- `1m` = 1 MB/s  
- `2000k` = 2 MB/s
- Numbers without suffix = KB/s

## Monitoring Impact

### Check Process Priority
```bash
# Find the scraper process
ps aux | grep subreddit_frontpage_scraper

# Check nice level (NI column)
ps -l -p <PID>
```

### Monitor Network Usage
```bash
# macOS - monitor network activity
nettop -p <PID>

# Linux - monitor bandwidth
iftop
nethogs
```

## Troubleshooting

### Permission Issues
If you get permission errors with `ionice`:
```bash
# The script will continue without I/O priority - this is normal on macOS
```

### Trickle Not Working
```bash
# Check if trickle is installed
which trickle

# Install trickle
brew install trickle  # macOS
sudo apt-get install trickle  # Linux
```

### Bandwidth Still High
- Ensure `--disable-images` is used (blocks 70-90% of bandwidth)
- Lower the bandwidth limit: `-b 200k` instead of `-b 1m`
- Check if multiple processes are running

## Performance Impact

### Without Low Priority
- May saturate network connection
- Can cause lag in video calls, streaming, etc.
- Competes with user applications for CPU

### With Low Priority  
- Automatically yields to user applications
- Network usage controlled and predictable
- Minimal impact on system responsiveness
- Scraping throughput barely affected

## Integration with Batch Scripts

```bash
# Add to existing batch processing
CONCURRENCY=2 ./scripts/run_frontpage_batch.sh --low-priority

# Custom wrapper in your own scripts
nice -n 15 trickle -d 500 -u 200 python subreddit_frontpage_scraper.py --subs "$@"
```

## Best Practices

1. **Always use `--disable-images`** for maximum bandwidth savings
2. **Use nice level 10-15** for background processing during work
3. **Use nice level 15-19** for overnight batch processing  
4. **Set bandwidth limits** when sharing connection with others
5. **Monitor system impact** initially to find optimal settings
6. **Use the shell wrapper** for maximum control and convenience

This ensures the scraper runs efficiently in the background without interfering with your important work!
