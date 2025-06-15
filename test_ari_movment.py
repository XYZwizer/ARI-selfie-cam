#!/usr/bin/env python3
"""
Simple test script for ARI robot shake_left motion
"""

import requests
import json
import time

# Robot configuration
ROBOT_URL = "http://192.168.0.103/action/motion_manager"

def execute_shake_left():
    """Execute shake_left motion and check status"""
    
    # Step 1: Execute the motion
    print("1. Executing shake_left motion...")
    payload = {"filename": "shake_left"}
    
    try:
        response = requests.post(ROBOT_URL, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            print("✓ Motion request successful!")
            print(f"Response: {json.dumps(result, indent=2)}")
            
            # Extract goal_id for status checking
            goal_id = result["response"]["goal_id"]
            print(f"Goal ID: {goal_id}")
            
            return goal_id
        else:
            print(f"✗ Motion request failed: {response.status_code}")
            print(f"Error: {response.text}")
            return None
            
    except Exception as e:
        print(f"✗ Error executing motion: {e}")
        return None

def check_motion_status(goal_id):
    """Check the status of the motion using goal_id"""
    
    print(f"\n2. Checking motion status...")
    status_url = f"{ROBOT_URL}?{goal_id}"
    
    try:
        response = requests.get(status_url)
        
        if response.status_code == 200:
            status_data = response.json()
            print("✓ Status check successful!")
            print(f"Status response: {json.dumps(status_data, indent=2)}")
            
            # Check if our goal_id is in the response
            if goal_id in status_data:
                status = status_data[goal_id]
                print(f"\nMotion Status: {status}")
                
                if status == "SUCCEEDED":
                    print("✓ Motion completed successfully!")
                elif status == "ACTIVE":
                    print("⏳ Motion is still running...")
                elif status == "ABORTED":
                    print("✗ Motion was aborted")
                else:
                    print(f"? Unknown status: {status}")
            else:
                print(f"Goal ID {goal_id} not found in status response")
                
        else:
            print(f"✗ Status check failed: {response.status_code}")
            print(f"Error: {response.text}")
            
    except Exception as e:
        print(f"✗ Error checking status: {e}")

def main():
    print("ARI Robot - Shake Left Test")
    print("=" * 30)
    
    # Execute the motion
    goal_id = execute_shake_left()
    
    if goal_id:
        # Wait a moment for the motion to start
        print("\nWaiting 2 seconds...")
        time.sleep(2)
        
        # Check the status
        check_motion_status(goal_id)
        
        # Check again after a longer wait
        print("\nWaiting 3 more seconds...")
        time.sleep(3)
        check_motion_status(goal_id)
    
    print("\nTest complete!")

if __name__ == "__main__":
    main()