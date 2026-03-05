#!/usr/bin/env python3
"""Update Aqara FP2 integration with Device ID"""

import json

device_id = "54EF4479E003"
config_path = "/config/.storage/core.config_entries"

# Load config entries
with open(config_path, 'r') as f:
    data = json.load(f)

# Find aqara_fp2 entry and update
found = False
for entry in data['data']['entries']:
    if entry.get('domain') == 'aqara_fp2':
        print(f"Found entry: {entry.get('entry_id')}")
        print(f"Current data: {entry.get('data', {})}")
        
        # Add device_id to data
        entry['data']['device_id'] = device_id
        
        print(f"Updated data: {entry.get('data', {})}")
        found = True
        break

if found:
    # Save back
    with open(config_path, 'w') as f:
        json.dump(data, f, indent=4)
    
    print("\n✅ Configuration updated successfully!")
    print(f"Device ID {device_id} added to integration")
else:
    print("❌ aqara_fp2 entry not found!")
