"""Serve the Recoil browser build and resolve its game archives."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlsplit

from content import DEFAULT_GAME, DEFAULT_MAP, prepare

PUBLIC = Path(__file__).resolve().parent / "public"
ENGINE = "2026.07.04"
lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, install=None, **kwargs):
        self.install = install
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)

    def respond(self, code, value):
        raw = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path == "/api/runtime":
            root = PUBLIC / "engine"
            ready = (root / "spring-web.wasm").is_file() and (root / "spring-web.js").is_file()
            files = []
            for folder in ("base", "fonts"):
                for file in sorted((root / folder).rglob("*")):
                    if file.suffix.lower() in (".sdz", ".otf"):
                        path = file.relative_to(root).as_posix()
                        files.append({"path": path, "url": "/engine/" + path,
                                      "size": file.stat().st_size, "id": str(file.stat().st_mtime_ns)})
            build = str((root / "spring-web.wasm").stat().st_mtime_ns) if ready else ""
            return self.respond(200, {"ready": ready and bool(files), "engine": ENGINE, "build": build,
                                      "game": DEFAULT_GAME, "map": DEFAULT_MAP, "files": files})
        if request.path != "/api/content":
            return super().do_GET()
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.respond(403, {"error": "Open the player to request game content."})
        params = parse_qs(request.query)
        kind, name = (params.get(k, [""])[0].strip() for k in ("kind", "name"))
        if kind not in ("map", "game") or not re.fullmatch(r"[^\x00-\x1f;{}\[\]/\\]{1,180}", name):
            return self.respond(400, {"error": "Invalid game or map name."})
        try:
            with lock:
                record = prepare(kind, name, PUBLIC / "content", self.install)
        except (ValueError, OSError, EOFError) as error:
            return self.respond(422, {"error": str(error)})
        return self.respond(200, {**record, "url": "/content/" + record["file"], "id": record["file"]})


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--port", type=int, default=8080)
    cli.add_argument("--host", default="127.0.0.1")
    cli.add_argument("--install", type=Path, help="Optional Zero-K install to reuse local maps and Rapid pool files.")
    args = cli.parse_args()
    steam = Path("C:/Program Files (x86)/Steam/steamapps/common/Zero-K")
    install = args.install or (steam if steam.is_dir() else None)
    mimetypes.add_type("application/wasm", ".wasm")
    mimetypes.add_type("text/javascript", ".js")
    server = ThreadingHTTPServer((args.host, args.port), partial(Handler, install=install))
    print(f"zk-online is listening on http://{args.host}:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
