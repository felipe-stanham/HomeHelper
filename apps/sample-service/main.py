#!/usr/bin/env python3
"""
Sample Service Application for HomeHelper

This is a simple FastAPI service that demonstrates the HomeHelper app structure.
"""

from fastapi import FastAPI
from pydantic import BaseModel
import os
import time
from datetime import datetime

# Create FastAPI app
app = FastAPI(
    title="Sample Service",
    description="Sample service application for HomeHelper testing",
    version="1.0.0"
)

# Sample data model
class StatusResponse(BaseModel):
    service: str
    status: str
    timestamp: str
    uptime_seconds: float

# Service start time
start_time = time.time()

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Sample Service is running",
        "service": "sample-service",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint required by HomeHelper"""
    return {
        "status": "healthy",
        "service": "sample-service",
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": time.time() - start_time
    }

@app.get("/ui")
async def ui_endpoint():
    """UI endpoint that returns data for HomeHelper dashboard"""
    return {
        "title": "Sample Service Dashboard",
        "data": [
            {
                "label": "Service Status",
                "value": "Running",
                "type": "status"
            },
            {
                "label": "Uptime",
                "value": f"{int(time.time() - start_time)} seconds",
                "type": "text"
            },
            {
                "label": "Environment",
                "value": os.getenv("SERVICE_NAME", "unknown"),
                "type": "text"
            },
            {
                "label": "Debug Mode",
                "value": os.getenv("DEBUG", "false"),
                "type": "boolean"
            }
        ],
        "actions": [
            {
                "label": "Restart Service",
                "endpoint": "/restart",
                "method": "POST"
            }
        ]
    }

@app.post("/restart")
async def restart_service():
    """Sample action endpoint"""
    global start_time
    start_time = time.time()
    return {
        "message": "Service restarted",
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port)
