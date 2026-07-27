from __future__ import annotations

import os


def main() -> int:
    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            "uvicorn is not installed. Install the web dependencies with:\n"
            "  python -m pip install -e '.[web]'\n"
        )
        return 1

    host = os.environ.get("GRIDLENS_API_HOST", "0.0.0.0")
    port = int(os.environ.get("GRIDLENS_API_PORT", "8000"))
    uvicorn.run("gridlens.webapi.app:create_app", factory=True, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

