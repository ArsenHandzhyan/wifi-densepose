#!/usr/bin/env python3
"""
Debug script to monitor FP2 coordinate changes in real-time.
Shows if coordinates are actually updating when you move.
"""

import requests
import time
import json

BACKEND_URL = "http://127.0.0.1:8000"

def main():
    print("🔍 FP2 Coordinate Debug Monitor")
    print("=" * 60)
    print("Monitoring coordinate updates from Aqara Cloud API...")
    print("Move in front of your FP2 sensor now!")
    print("=" * 60)
    print()
    
    last_coords = None
    last_movement = None
    sample_count = 0
    
    try:
        while True:
            sample_count += 1
            
            # Fetch current data
            try:
                response = requests.get(f"{BACKEND_URL}/api/v1/fp2/current", timeout=5)
                response.raise_for_status()
            except Exception as e:
                print(f"❌ Backend error: {e}")
                time.sleep(2)
                continue
            
            data = response.json()
            metadata = data.get('metadata', {})
            raw_attrs = metadata.get('raw_attributes', {})
            
            # Extract key fields
            movement_event = raw_attrs.get('movement_event')
            presence = raw_attrs.get('presence')
            coordinates = raw_attrs.get('coordinates', [])
            resource_values = raw_attrs.get('resource_values', {})
            coords_payload = resource_values.get('4.22.700', '[]')
            
            # Parse coordinates
            try:
                coords = json.loads(coords_payload) if isinstance(coords_payload, str) else coords_payload
                active_coords = [c for c in coords if c.get('state') == '1' and (c.get('x', 0) != 0 or c.get('y', 0) != 0)]
            except:
                active_coords = []
            
            # Build coordinate signature
            coord_sig = [(c.get('id'), c.get('x'), c.get('y')) for c in active_coords]
            
            # Detect changes
            movement_changed = movement_event != last_movement
            coords_changed = coord_sig != last_coords
            
            # Print status
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] Sample #{sample_count}")
            print(f"  Presence: {presence}")
            print(f"  Movement Event: {movement_event} {'← CHANGED' if movement_changed else ''}")
            print(f"  Active Targets: {len(active_coords)}")
            
            if active_coords:
                for c in active_coords:
                    print(f"    - Target {c.get('id')}: ({c.get('x')}, {c.get('y')})")
                
                if coords_changed:
                    print(f"  ⚡ COORDINATES UPDATED!")
                else:
                    print(f"  ⏸️  Coordinates STABLE (no change)")
            else:
                print(f"  ⚠️  No active coordinates")
            
            # Show raw 4.22.700 payload occasionally
            if sample_count % 5 == 0:
                print(f"\n  Raw 4.22.700 payload:")
                print(f"  {coords_payload[:200]}...")
            
            print()
            
            # Update state
            last_coords = coord_sig
            last_movement = movement_event
            
            # Wait before next sample
            time.sleep(1.5)
            
    except KeyboardInterrupt:
        print("\n\nStopped by user")
        print(f"Total samples: {sample_count}")
        print(f"Coordinate changes: detected")

if __name__ == "__main__":
    main()
