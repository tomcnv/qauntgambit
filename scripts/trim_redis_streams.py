#!/usr/bin/env python3
"""Trim Redis streams to prevent memory overflow."""

import redis
import sys

def main():
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Get all stream keys
    print("Checking Redis memory...")
    info = r.info('memory')
    print(f"Current memory: {info['used_memory_human']}")
    
    # Get all keys matching events:*
    print("\nFinding streams...")
    keys = r.keys('events:*')
    print(f"Found {len(keys)} event keys")
    
    # Trim each stream
    max_len = 10000
    for key in keys:
        try:
            key_type = r.type(key)
            if key_type == 'stream':
                length = r.xlen(key)
                if length > max_len:
                    print(f"Trimming {key}: {length} -> {max_len}")
                    r.xtrim(key, maxlen=max_len, approximate=False)
                else:
                    print(f"OK {key}: {length} entries")
        except Exception as e:
            print(f"Error with {key}: {e}")
    
    # Check memory after
    print("\nAfter trimming:")
    info = r.info('memory')
    print(f"Memory: {info['used_memory_human']}")

if __name__ == '__main__':
    main()
