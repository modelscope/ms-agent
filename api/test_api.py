#!/usr/bin/env python3
# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Simple test script for API functionality
Run this after starting the API server to verify basic functionality
"""
import asyncio
import json
import requests
import websockets


BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"


def test_health():
    """Test health endpoint"""
    print("\n=== Testing Health Endpoint ===")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✓ Health check passed")


def test_config():
    """Test configuration endpoints"""
    print("\n=== Testing Configuration ===")
    
    # Get all config
    response = requests.get(f"{BASE_URL}/api/v1/config")
    print(f"Status: {response.status_code}")
    assert response.status_code == 200
    print("✓ Get all config passed")
    
    # Get LLM config
    response = requests.get(f"{BASE_URL}/api/v1/config/llm")
    print(f"Status: {response.status_code}")
    assert response.status_code == 200
    print("✓ Get LLM config passed")


def test_projects():
    """Test project endpoints"""
    print("\n=== Testing Projects ===")
    
    # List projects
    response = requests.get(f"{BASE_URL}/api/v1/projects")
    print(f"Status: {response.status_code}")
    assert response.status_code == 200
    data = response.json()
    projects = data.get('data', [])
    print(f"Found {len(projects)} projects")
    for project in projects[:3]:
        print(f"  - {project['display_name']} ({project['type']})")
    print("✓ List projects passed")
    
    return projects


def test_sessions():
    """Test session endpoints"""
    print("\n=== Testing Sessions ===")
    
    # Create session
    response = requests.post(f"{BASE_URL}/api/v1/sessions", json={
        'project_id': 'chat',
        'session_type': 'chat'
    })
    print(f"Status: {response.status_code}")
    assert response.status_code == 200
    data = response.json()
    session_id = data['data']['id']
    print(f"Created session: {session_id}")
    
    # Get session
    response = requests.get(f"{BASE_URL}/api/v1/sessions/{session_id}")
    print(f"Status: {response.status_code}")
    assert response.status_code == 200
    print("✓ Get session passed")
    
    # List sessions
    response = requests.get(f"{BASE_URL}/api/v1/sessions")
    print(f"Status: {response.status_code}")
    assert response.status_code == 200
    print("✓ List sessions passed")
    
    return session_id


def test_agent_status(session_id):
    """Test agent status endpoint"""
    print("\n=== Testing Agent Status ===")
    
    response = requests.get(f"{BASE_URL}/api/v1/agent/status/{session_id}")
    print(f"Status: {response.status_code}")
    assert response.status_code == 200
    data = response.json()
    print(f"Agent status: {data['data']['status']}")
    print("✓ Agent status check passed")


async def test_websocket_connection(session_id):
    """Test WebSocket connection"""
    print("\n=== Testing WebSocket Connection ===")
    
    uri = f"{WS_URL}/ws/agent/{session_id}"
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Connected to {uri}")
            
            # Wait for connection message
            message = await websocket.recv()
            data = json.loads(message)
            print(f"Received: {data['type']}")
            assert data['type'] == 'connected'
            
            # Send ping
            await websocket.send(json.dumps({'type': 'ping'}))
            message = await websocket.recv()
            data = json.loads(message)
            print(f"Ping response: {data['type']}")
            assert data['type'] == 'pong'
            
            print("✓ WebSocket connection test passed")
    except Exception as e:
        print(f"✗ WebSocket test failed: {e}")


def cleanup_session(session_id):
    """Clean up test session"""
    print(f"\n=== Cleaning up session {session_id} ===")
    response = requests.delete(f"{BASE_URL}/api/v1/sessions/{session_id}")
    if response.status_code == 200:
        print("✓ Session deleted")
    else:
        print(f"⚠ Failed to delete session: {response.status_code}")


def main():
    """Run all tests"""
    print("=" * 60)
    print("MS-Agent API Test Suite")
    print("=" * 60)
    print("\nMake sure the API server is running on http://localhost:8000")
    print("Start it with: python api/run_server.py")
    
    try:
        test_health()
        test_config()
        projects = test_projects()
        session_id = test_sessions()
        test_agent_status(session_id)
        
        # Test WebSocket
        asyncio.run(test_websocket_connection(session_id))
        
        # Cleanup
        cleanup_session(session_id)
        
        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        
    except requests.exceptions.ConnectionError:
        print("\n✗ Error: Could not connect to API server")
        print("Please start the server with: python api/run_server.py")
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")


if __name__ == '__main__':
    main()
