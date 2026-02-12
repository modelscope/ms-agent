# Copyright (c) Alibaba, Inc. and its affiliates.
"""
MS-Agent API Server
Main application entry point
"""
import os
import sys
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Import routers
from .config import router as config_router
from .project import router as project_router
from .session import router as session_router
from .agent import router as agent_router
from .websocket import router as websocket_router
from .files import router as files_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI application
app = FastAPI(
    title='MS-Agent API Server',
    description='REST API and WebSocket endpoints for MS-Agent framework',
    version='1.0.0',
    docs_url='/api/docs',
    redoc_url='/api/redoc'
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Include API routers
app.include_router(config_router)
app.include_router(project_router)
app.include_router(session_router)
app.include_router(agent_router)
app.include_router(websocket_router)
app.include_router(files_router)


# Root endpoint
@app.get('/')
async def root():
    """Root endpoint with API information"""
    return {
        'name': 'MS-Agent API Server',
        'version': '1.0.0',
        'description': 'REST API and WebSocket endpoints for MS-Agent framework',
        'status': 'running',
        'endpoints': {
            'config': '/api/v1/config',
            'projects': '/api/v1/projects',
            'sessions': '/api/v1/sessions',
            'agent': '/api/v1/agent',
            'files': '/api/v1/files',
            'websocket_agent': '/ws/agent/{session_id}',
            'websocket_chat': '/ws/chat'
        },
        'documentation': {
            'swagger': '/api/docs',
            'redoc': '/api/redoc'
        }
    }


@app.get('/health')
async def health_check():
    """Health check endpoint"""
    return {
        'status': 'healthy',
        'services': {
            'api': 'running',
            'websocket': 'available'
        }
    }


@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Custom 404 error handler"""
    logger.warning(f"404 Not Found: {request.url}")
    return JSONResponse(
        status_code=404,
        content={
            'success': False,
            'error': {
                'code': 'NOT_FOUND',
                'message': 'The requested resource was not found',
                'path': str(request.url)
            }
        }
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Custom 500 error handler"""
    logger.error(f"Internal server error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            'success': False,
            'error': {
                'code': 'INTERNAL_ERROR',
                'message': 'An internal server error occurred',
                'details': str(exc)
            }
        }
    )


def main():
    """Start the API server"""
    import argparse
    
    parser = argparse.ArgumentParser(description='MS-Agent API Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind')
    parser.add_argument('--port', type=int, default=8000, help='Port to bind')
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload')
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print('  MS-Agent API Server')
    print(f"{'='*60}")
    print(f'  Server running at: http://{args.host}:{args.port}')
    print(f'  API documentation: http://{args.host}:{args.port}/api/docs')
    print(f'  WebSocket endpoints:')
    print(f'    - Agent: ws://{args.host}:{args.port}/ws/agent/{{session_id}}')
    print(f'    - Chat: ws://{args.host}:{args.port}/ws/chat')
    print(f"{'='*60}\n")
    
    uvicorn.run(
        'api.main:app',
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level='info'
    )


if __name__ == '__main__':
    main()
