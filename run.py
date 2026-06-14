#!/usr/bin/env python
"""Launch the Folio web UI.  Run:  python run.py   then open http://localhost:8800"""

import webbrowser

import uvicorn

if __name__ == "__main__":
    url = "http://localhost:8800"
    print(f"\n  Folio is starting...  Open  {url}  in your browser.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run("server.main:app", host="127.0.0.1", port=8800, log_level="info")
