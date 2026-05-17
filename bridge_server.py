#!/usr/bin/env python3
"""
ANBM Bridge Server v2
Zero-dependency HTTP relay between Chrome extension and Cowork VM.
Listens on localhost:8765.
"""

import argparse, json, os, sys, time, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

parser = argparse.ArgumentParser(description="ANBM Bridge Server")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--workspace", type=str,
                    default=os.path.dirname(os.path.abspath(__file__)))
args = parser.parse_args()

WORKSPACE = Path(args.workspace).resolve()
BRIDGE_DIR = WORKSPACE / ".bridge"
SITES_DIR = BRIDGE_DIR / "sites"
TASKS_DIR = BRIDGE_DIR / "tasks"
RESULTS_DIR = BRIDGE_DIR / "results"
ADAPTERS_DIR = BRIDGE_DIR / "adapters"

for d in [SITES_DIR, TASKS_DIR, RESULTS_DIR, ADAPTERS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

start_time = time.time()

class BridgeHandler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message, status=400):
        self._json({"ok": False, "error": message}, status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        try:
            if path == "/health":
                tasks_pending = len(list(TASKS_DIR.glob("*.json")))
                snapshots = sum(1 for d in SITES_DIR.iterdir()
                                if any(d.glob("dom_snapshot*.json")))
                self._json({
                    "ok": True,
                    "uptime_seconds": int(time.time() - start_time),
                    "tasks_pending": tasks_pending,
                    "snapshots_received": snapshots,
                    "workspace": str(WORKSPACE),
                })

            elif path == "/tasks":
                adapter_id = qs.get("adapter_id", [None])[0]
                for f in sorted(TASKS_DIR.glob("*.json")):
                    try:
                        task = json.loads(f.read_text("utf-8"))
                    except Exception:
                        continue
                    if task.get("state") != "pending":
                        continue
                    if adapter_id and task.get("adapter_id") != adapter_id:
                        continue
                    task["state"] = "in_progress"
                    task["dispatched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    f.write_text(json.dumps(task, ensure_ascii=False, indent=2), "utf-8")
                    self._json(task)
                    return
                self._json({"task_id": None, "message": "no pending tasks"})

            elif path.startswith("/sites/"):
                rel = path[len("/sites/"):]
                filepath = SITES_DIR / rel
                if ".." in rel or not filepath.resolve().is_relative_to(SITES_DIR.resolve()):
                    self._error("invalid path", 400); return
                if not filepath.exists():
                    self._error("not found", 404); return
                data = json.loads(filepath.read_text("utf-8"))
                self._json(data)

            elif path == "/adapters":
                adapter_list = []
                project_adapters = WORKSPACE / "adapters"
                if project_adapters.exists():
                    for d in sorted(project_adapters.iterdir()):
                        if not d.is_dir(): continue
                        mf = d / "manifest.json"
                        if not mf.exists(): continue
                        try:
                            manifest = json.loads(mf.read_text("utf-8"))
                        except Exception:
                            manifest = {}
                        verified = bool(manifest.get("last_verified"))
                        adapter_list.append({
                            "id": d.name,
                            "name": manifest.get("name", d.name),
                            "manifest": manifest,
                            "verified": verified,
                        })
                self._json({"adapters": adapter_list})

            elif path.startswith("/adapters/"):
                rel = path[len("/adapters/"):]
                filepath = ADAPTERS_DIR / rel
                if ".." in rel or not filepath.resolve().is_relative_to(ADAPTERS_DIR.resolve()):
                    self._error("invalid path", 400); return
                if not filepath.exists():
                    self._error("not found", 404); return
                body = filepath.read_text("utf-8")
                self.send_response(200); self._cors()
                if filepath.suffix == ".json":
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                else:
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                encoded = body.encode("utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers(); self.wfile.write(encoded)
            else:
                self._error("not found", 404)
        except Exception as e:
            traceback.print_exc()
            self._error(str(e), 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            body = self._read_body()
            if path == "/snapshot":
                adapter_id = body.get("adapter_id", "unknown")
                state_hint = body.get("state_hint") or ""
                batch_scan = body.get("batch_scan", False)
                site_dir = SITES_DIR / adapter_id
                site_dir.mkdir(parents=True, exist_ok=True)
                if state_hint:
                    safe = state_hint.replace("/", "_").replace("\\", "_")[:50]
                    fname = f"dom_snapshot_{safe}.json"
                elif batch_scan:
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    fname = f"dom_snapshot_{ts}.json"
                else:
                    fname = "dom_snapshot.json"
                snapshot_path = site_dir / fname
                snapshot_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), "utf-8")
                ts = body.get("timestamp", "")
                n_el = len(body.get("elements", []))
                print(f"[SNAPSHOT] {adapter_id} | {body.get('url','')[:80]} | {n_el} elements | {ts} | {fname}")
                self._json({"ok": True, "path": str(snapshot_path.relative_to(WORKSPACE)),
                            "task_count": len(list(TASKS_DIR.glob("*.json")))})

            elif path == "/selector-result":
                task_id = body.get("task_id", "unknown")
                result_path = RESULTS_DIR / f"{task_id}.json"
                body["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                result_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), "utf-8")
                task_path = TASKS_DIR / f"{task_id}.json"
                if task_path.exists():
                    task = json.loads(task_path.read_text("utf-8"))
                    task["state"] = "completed"
                    task["completed_at"] = body["completed_at"]
                    task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), "utf-8")
                n_results = len(body.get("results", []))
                n_found = sum(1 for r in body.get("results", []) if r.get("found"))
                print(f"[RESULT] {task_id} | {n_found}/{n_results} selectors found")
                self._json({"ok": True})

            elif path == "/task-status":
                task_id = body.get("task_id", "")
                status = body.get("status", "")
                print(f"[TASK-STATUS] {task_id} -> {status} {body.get('message','')}")
                self._json({"ok": True})

            elif path == "/adapter":
                adapter_id = body.get("adapter_id")
                manifest = body.get("manifest")
                handler = body.get("handler")
                if not adapter_id: self._error("missing adapter_id", 400); return
                adapter_dir = ADAPTERS_DIR / adapter_id
                adapter_dir.mkdir(parents=True, exist_ok=True)
                if manifest:
                    (adapter_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
                if handler:
                    (adapter_dir / "handler.py").write_text(handler, "utf-8")
                print(f"[ADAPTER] {adapter_id} written")
                self._json({"ok": True, "path": str(adapter_dir.relative_to(WORKSPACE))})
            else:
                self._error("not found", 404)
        except json.JSONDecodeError:
            self._error("invalid JSON body", 400)
        except Exception as e:
            traceback.print_exc()
            self._error(str(e), 500)

def main():
    server = HTTPServer(("127.0.0.1", args.port), BridgeHandler)
    print(f"ANBM Bridge Server v2")
    print(f"  listening: http://localhost:{args.port}")
    print(f"  workspace:  {WORKSPACE}")
    print(f"  Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()
