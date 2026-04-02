"""
Example Companion App — Minimal Latarnia service app.

Used as a dependency target for example_full_app to demonstrate
the `requires` manifest field.
"""

import argparse
from datetime import datetime

import uvicorn
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def health():
    return {
        "health": "good",
        "message": "Companion app is running",
        "extra_info": {"started_at": datetime.now().isoformat()},
    }


def main():
    parser = argparse.ArgumentParser(description="Example Companion App")
    parser.add_argument("--port", type=int, default=8100, help="HTTP port")
    args = parser.parse_args()
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
