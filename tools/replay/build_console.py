#!/usr/bin/env python3
"""Assemble the static Reliability Console into site-console/ for Vercel/Pages.

The design HTML (demo/) is the single source of truth. The static build wires
it to recording-data.js (the real captured session); the live /demoboard route
wires the same HTML to live-data.js. No duplicated board code.

    python3 tools/replay/build_console.py     # -> site-console/

Deploy:  cd site-console && vercel --prod   (or push; Pages workflow handles it)
"""
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "demo"
OUT = REPO / "site-console"


def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    # board pages: operate (index) + deploy + roadmap, wired to the recording
    board = (DEMO / "devboard.html").read_text().replace(
        "mock-data.js", "recording-data.js")
    (OUT / "index.html").write_text(board)
    deploy = (DEMO / "deploy.html").read_text().replace(
        "mock-data.js", "recording-data.js")
    (OUT / "deploy.html").write_text(deploy)
    shutil.copy(DEMO / "roadmap.html", OUT / "roadmap.html")

    # data source + assets
    shutil.copy(DEMO / "recording-data.js", OUT / "recording-data.js")
    shutil.copy(DEMO / "tokens.css", OUT / "tokens.css")
    shutil.copy(REPO / "site" / "session-recording.json",
                OUT / "session-recording.json")

    # evidence replay lives under /replay
    (OUT / "replay").mkdir()
    shutil.copy(REPO / "site" / "index.html", OUT / "replay" / "index.html")
    shutil.copy(REPO / "site" / "replay-data.js",
                OUT / "replay" / "replay-data.js")

    (OUT / "vercel.json").write_text(
        '{\n  "version": 2,\n  "public": true,\n'
        '  "cleanUrls": true\n}\n')

    rec = (OUT / "session-recording.json").stat().st_size // 1024
    print(f"built {OUT.relative_to(REPO)}/ — "
          f"index+deploy+roadmap, recording {rec}KB, /replay")
    print("deploy:  cd site-console && vercel --prod")


if __name__ == "__main__":
    build()
