#!/usr/bin/env python
# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Test script for new API endpoints
Tests the newly added functionality from webui/backend
"""
import requests
import json
from typing import Dict, Any

BASE_URL = "http://localhost:8000"


def print_response(response, endpoint: str):
    """Print response information"""
    print(f"\n{'='*60}")
    print(f"Endpoint: {endpoint}")
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except:
        print(f"Response: {response.text}")
    print(f"{'='*60}")


def test_config_endpoints():
    """Test configuration endpoints"""
    print("\n\n### Testing Configuration Endpoints ###\n")
    
    # 1. Get all config
    print("1. Get all configuration")
    r = requests.get(f"{BASE_URL}/api/v1/config")
    print_response(r, "GET /api/v1/config")
    
    # 2. Get available models
    print("\n2. Get available models")
    r = requests.get(f"{BASE_URL}/api/v1/config/models")
    print_response(r, "GET /api/v1/config/models")
    
    # 3. Get MCP config
    print("\n3. Get MCP servers configuration")
    r = requests.get(f"{BASE_URL}/api/v1/config/mcp")
    print_response(r, "GET /api/v1/config/mcp")
    
    # 4. Add MCP server (example)
    print("\n4. Add MCP server (test)")
    test_server = {
        "name": "test-server",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"]
    }
    r = requests.post(f"{BASE_URL}/api/v1/config/mcp/servers", json=test_server)
    print_response(r, "POST /api/v1/config/mcp/servers")
    
    # 5. Get EdgeOne Pages config
    print("\n5. Get EdgeOne Pages configuration")
    r = requests.get(f"{BASE_URL}/api/v1/config/edgeone-pages")
    print_response(r, "GET /api/v1/config/edgeone-pages")
    
    # 6. Get Deep Research config
    print("\n6. Get Deep Research configuration")
    r = requests.get(f"{BASE_URL}/api/v1/config/deep-research")
    print_response(r, "GET /api/v1/config/deep-research")
    
    # 7. Update Deep Research config (example)
    print("\n7. Update Deep Research configuration")
    dr_config = {
        "researcher": {
            "model": "qwen-plus",
            "api_key": "test-key",
            "base_url": "https://api.example.com"
        },
        "searcher": {
            "model": "qwen-plus",
            "api_key": "test-key",
            "base_url": "https://api.example.com"
        },
        "reporter": {
            "model": "qwen-plus",
            "api_key": "test-key",
            "base_url": "https://api.example.com"
        },
        "search": {
            "summarizer_model": "qwen-plus",
            "summarizer_api_key": "test-key",
            "summarizer_base_url": "https://api.example.com"
        }
    }
    r = requests.put(f"{BASE_URL}/api/v1/config/deep-research", json=dr_config)
    print_response(r, "PUT /api/v1/config/deep-research")
    
    # 8. Get config status
    print("\n8. Get configuration status")
    r = requests.get(f"{BASE_URL}/api/v1/config/status")
    print_response(r, "GET /api/v1/config/status")


def test_project_endpoints():
    """Test project endpoints"""
    print("\n\n### Testing Project Endpoints ###\n")
    
    # 1. List projects
    print("1. List all projects")
    r = requests.get(f"{BASE_URL}/api/v1/projects")
    print_response(r, "GET /api/v1/projects")
    
    projects = r.json().get('data', [])
    if not projects:
        print("No projects found, skipping workflow test")
        return
    
    # 2. Get project workflow (use first project that supports workflow)
    for project in projects:
        if project.get('type') == 'workflow':
            project_id = project['id']
            print(f"\n2. Get workflow for project: {project_id}")
            r = requests.get(f"{BASE_URL}/api/v1/projects/{project_id}/workflow")
            print_response(r, f"GET /api/v1/projects/{project_id}/workflow")
            break


def test_file_endpoints():
    """Test file operation endpoints"""
    print("\n\n### Testing File Endpoints ###\n")
    
    # 1. List files
    print("1. List files in output directory")
    r = requests.get(f"{BASE_URL}/api/v1/files/list?root_dir=output")
    print_response(r, "GET /api/v1/files/list")
    
    # 2. Try to read a file (if any exists)
    try:
        data = r.json().get('data', {})
        tree = data.get('tree', {})
        files = tree.get('files', [])
        
        if files:
            file_path = files[0]['path']
            print(f"\n2. Read file: {file_path}")
            read_request = {
                "path": file_path,
                "root_dir": "output"
            }
            r = requests.post(f"{BASE_URL}/api/v1/files/read", json=read_request)
            print_response(r, "POST /api/v1/files/read")
        else:
            print("\n2. No files found to read")
    except Exception as e:
        print(f"\n2. Error reading file: {e}")


def test_session_endpoints():
    """Test session endpoints"""
    print("\n\n### Testing Session Endpoints ###\n")
    
    # 1. Create a session
    print("1. Create a new session")
    session_data = {
        "project_id": "chat",
        "session_type": "chat"
    }
    r = requests.post(f"{BASE_URL}/api/v1/sessions", json=session_data)
    print_response(r, "POST /api/v1/sessions")
    
    if r.status_code == 200:
        session_id = r.json().get('data', {}).get('id')
        
        # 2. Get session
        print(f"\n2. Get session: {session_id}")
        r = requests.get(f"{BASE_URL}/api/v1/sessions/{session_id}")
        print_response(r, f"GET /api/v1/sessions/{session_id}")
        
        # 3. Get session messages
        print(f"\n3. Get session messages: {session_id}")
        r = requests.get(f"{BASE_URL}/api/v1/sessions/{session_id}/messages")
        print_response(r, f"GET /api/v1/sessions/{session_id}/messages")
        
        # 4. Delete session
        print(f"\n4. Delete session: {session_id}")
        r = requests.delete(f"{BASE_URL}/api/v1/sessions/{session_id}")
        print_response(r, f"DELETE /api/v1/sessions/{session_id}")


def main():
    """Run all tests"""
    print("="*60)
    print("Testing New API Endpoints")
    print("Make sure the API server is running on http://localhost:8000")
    print("="*60)
    
    try:
        # Test if server is running
        r = requests.get(f"{BASE_URL}/health")
        if r.status_code != 200:
            print("Error: API server is not responding")
            return
        
        # Run tests
        test_config_endpoints()
        test_project_endpoints()
        test_file_endpoints()
        test_session_endpoints()
        
        print("\n\n" + "="*60)
        print("All tests completed!")
        print("="*60)
        
    except requests.exceptions.ConnectionError:
        print("\nError: Cannot connect to API server")
        print("Please make sure the server is running:")
        print("  cd api")
        print("  python -m api.main --port 8000")
    except Exception as e:
        print(f"\nError during testing: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
