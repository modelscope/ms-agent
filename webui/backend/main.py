# Copyright (c) Alibaba, Inc. and its affiliates.
"""
MS-Agent Web UI Backend Server
Provides REST API and WebSocket endpoints for the ms-agent framework.
"""
import os
import sys
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api import router as api_router
from websocket_handler import router as ws_router

# Add ms-agent to path
MS_AGENT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'ms-agent'))
if MS_AGENT_PATH not in sys.path:
    sys.path.insert(0, MS_AGENT_PATH)

app = FastAPI(
    title="MS-Agent Web UI",
    description="Web interface for the MS-Agent framework",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API and WebSocket routers
app.include_router(api_router, prefix="/api")
app.include_router(ws_router, prefix="/ws")

# Serve static files in production
STATIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
if os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA for all non-API routes"""
        file_path = os.path.join(STATIC_DIR, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "ms-agent-webui"}


def main():
    """Start the server"""
    import argparse
    parser = argparse.ArgumentParser(description="MS-Agent Web UI Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=7860, help="Port to bind")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print("  MS-Agent Web UI Server")
    print(f"{'='*60}")
    print(f"  Server running at: http://{args.host}:{args.port}")
    print(f"  API documentation: http://{args.host}:{args.port}/docs")
    print(f"{'='*60}\n")
    
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload
    )


if __name__ == "__main__":
    main()
