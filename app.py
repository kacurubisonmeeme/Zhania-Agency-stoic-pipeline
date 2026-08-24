"""
app.py — Deployment Web Server & REST API for Stoic Shorts AI Pipeline.

Provides a lightweight, zero-dependency Python HTTP API server and static web host
for controlling orchestrator.py, streaming logs, serving videos, and displaying telemetry.

Usage:
    python app.py [--port 8000]
"""

import argparse
import csv
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
OUTPUTS_DIR = BASE_DIR / "outputs"
CSV_PATH = BASE_DIR / "stoic_quotes_database.csv"
USED_PATH = BASE_DIR / "used_quotes.json"
TELEMETRY_PATH = BASE_DIR / "telemetry_run.json"

# State management for pipeline execution thread
pipeline_state = {
    "status": "idle",       # "idle", "running", "completed", "failed"
    "theme": None,
    "no_download": False,
    "no_captions": False,
    "start_time": None,
    "end_time": None,
    "logs": [],             # list of log string lines
    "current_step": None,   # active module name
    "error": None,
    "returncode": None,
    "latest_output": None
}
state_lock = threading.Lock()


def append_log(line: str):
    with state_lock:
        pipeline_state["logs"].append(line)
        # Parse active step from orchestrator stdout format: "  [module_name]"
        match = re.search(r"^\s*\[([a_z0_9_]+)\]", line, re.IGNORECASE)
        if match:
            pipeline_state["current_step"] = match.group(1)


def run_orchestrator_worker(theme: str | None, no_download: bool, no_captions: bool):
    cmd = [sys.executable, str(BASE_DIR / "orchestrator.py")]
    if theme:
        cmd.extend(["--theme", theme])
    if no_download:
        cmd.append("--no-download")
    if no_captions:
        cmd.append("--no-captions")

    with state_lock:
        pipeline_state["status"] = "running"
        pipeline_state["theme"] = theme
        pipeline_state["no_download"] = no_download
        pipeline_state["no_captions"] = no_captions
        pipeline_state["start_time"] = time.time()
        pipeline_state["end_time"] = None
        pipeline_state["logs"] = []
        pipeline_state["current_step"] = "quote_picker"
        pipeline_state["error"] = None
        pipeline_state["returncode"] = None

    append_log(f"Starting pipeline runner command: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in proc.stdout:
            append_log(line.rstrip("\r\n"))

        proc.wait()

        with state_lock:
            pipeline_state["end_time"] = time.time()
            pipeline_state["returncode"] = proc.returncode
            if proc.returncode == 0:
                pipeline_state["status"] = "completed"
                pipeline_state["current_step"] = "complete"
                append_log("Pipeline completed successfully!")
            else:
                pipeline_state["status"] = "failed"
                pipeline_state["error"] = f"Exited with code {proc.returncode}"
                append_log(f"Pipeline failed with exit code {proc.returncode}")

    except Exception as exc:
        with state_lock:
            pipeline_state["status"] = "failed"
            pipeline_state["end_time"] = time.time()
            pipeline_state["error"] = str(exc)
            append_log(f"Exception while running pipeline: {exc}")


def get_quotes_data():
    quotes = []
    themes = set()
    if CSV_PATH.exists():
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item = {k: v.strip() for k, v in row.items()}
                quotes.append(item)
                if item.get("theme"):
                    themes.add(item["theme"])

    used = {}
    if USED_PATH.exists():
        try:
            used = json.loads(USED_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "quotes": quotes,
        "themes": sorted(list(themes)),
        "used": used,
        "total_quotes": len(quotes)
    }


def get_videos_data():
    videos = []
    if OUTPUTS_DIR.exists():
        for path in sorted(OUTPUTS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            stat = path.stat()
            videos.append({
                "filename": path.name,
                "url": f"/outputs/{path.name}",
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "timestamp": stat.st_mtime
            })
    return videos


def get_telemetry_data():
    if TELEMETRY_PATH.exists():
        try:
            data = json.loads(TELEMETRY_PATH.read_text(encoding="utf-8"))
            api_calls = data.get("api_calls", [])
            total_prompt = sum(c.get("prompt_tokens", 0) for c in api_calls)
            total_cand = sum(c.get("candidates_tokens", 0) for c in api_calls)
            total_tokens = sum(c.get("total_tokens", 0) for c in api_calls)
            thumb_b = data.get("thumbnail_bytes", 0)
            broll_b = data.get("broll_bytes", 0)
            
            return {
                "api_calls_count": len(api_calls),
                "api_calls": api_calls,
                "prompt_tokens": total_prompt,
                "candidates_tokens": total_cand,
                "total_tokens": total_tokens,
                "thumbnail_mb": round(thumb_b / (1024 * 1024), 2),
                "broll_mb": round(broll_b / (1024 * 1024), 2),
                "total_download_mb": round((thumb_b + broll_b) / (1024 * 1024), 2)
            }
        except Exception:
            pass
    return {"api_calls_count": 0, "total_tokens": 0, "total_download_mb": 0}


class ServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Quiet standard logging to avoid spamming console
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # REST API Routes
        if path == "/api/status":
            with state_lock:
                state_copy = dict(pipeline_state)
            videos = get_videos_data()
            state_copy["latest_video"] = videos[0] if videos else None
            self.send_json(state_copy)
            return

        if path == "/api/quotes":
            self.send_json(get_quotes_data())
            return

        if path == "/api/videos":
            self.send_json(get_videos_data())
            return

        if path == "/api/telemetry":
            self.send_json(get_telemetry_data())
            return

        # Serving static media files from outputs/
        if path.startswith("/outputs/"):
            filename = os.path.basename(path)
            target_path = OUTPUTS_DIR / filename
            if target_path.exists() and target_path.is_file():
                self.serve_file(target_path, content_type="video/mp4")
            else:
                self.send_error(404, "Video File Not Found")
            return

        # Serving dashboard static assets
        if path == "/" or path == "/index.html":
            target_path = STATIC_DIR / "index.html"
        else:
            rel_path = path.lstrip("/")
            target_path = STATIC_DIR / rel_path

        if target_path.exists() and target_path.is_file():
            mime_type, _ = mimetypes.guess_type(str(target_path))
            self.serve_file(target_path, content_type=mime_type or "text/plain")
        else:
            # Fallback to index.html for SPA routing if needed
            index_path = STATIC_DIR / "index.html"
            if index_path.exists():
                self.serve_file(index_path, content_type="text/html")
            else:
                self.send_error(404, "File Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/generate":
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw_body.decode("utf-8"))
            except Exception:
                body = {}

            with state_lock:
                if pipeline_state["status"] == "running":
                    self.send_json({"error": "Pipeline is already running"}, code=400)
                    return

            theme = body.get("theme")
            no_download = bool(body.get("no_download", False))
            no_captions = bool(body.get("no_captions", False))

            thread = threading.Thread(
                target=run_orchestrator_worker,
                args=(theme, no_download, no_captions),
                daemon=True
            )
            thread.start()

            self.send_json({
                "message": "Pipeline run launched successfully",
                "theme": theme,
                "no_download": no_download,
                "no_captions": no_captions
            })
            return

        self.send_error(404, "Endpoint Not Found")

    def serve_file(self, file_path: Path, content_type: str):
        try:
            file_size = file_path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    self.wfile.write(chunk)
        except Exception as exc:
            pass


def main():
    parser = argparse.ArgumentParser(description="Stoic AI Pipeline Web Deployment Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to run web server on (default: 8000)")
    args = parser.parse_args()

    # Ensure static and outputs folders exist
    STATIC_DIR.mkdir(exist_ok=True)
    OUTPUTS_DIR.mkdir(exist_ok=True)

    server_address = ("", args.port)
    httpd = HTTPServer(server_address, ServerHandler)
    print(f"=" * 60)
    print(f"  STOIC AI PIPELINE MODEL DEPLOYMENT SERVER")
    print(f"  Running on: http://localhost:{args.port}")
    print(f"  API Docs   : http://localhost:{args.port}/api/status")
    print(f"=" * 60)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()


if __name__ == "__main__":
    main()
