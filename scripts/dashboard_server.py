"""EigenCapital Dashboard Server — Launch the FastAPI dashboard API.

Usage:
    python scripts/dashboard_server.py              # Default: port 8080
    python scripts/dashboard_server.py --port 9000  # Custom port
    python scripts/dashboard_server.py --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="EigenCapital Dashboard Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is required. Install with: pip install uvicorn[standard]")
        sys.exit(1)

    print(f"Starting EigenCapital Dashboard on http://{args.host}:{args.port}")
    print("API docs: http://localhost:{args.port}/api/docs")
    print("Read-only mode: Dashboard cannot modify trading state")

    uvicorn.run(
        "eigencapital.dashboard.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(Path(__file__).parent.parent / "src")],
        log_level="info",
    )


if __name__ == "__main__":
    main()
