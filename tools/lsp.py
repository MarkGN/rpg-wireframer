#!/usr/bin/env python3
import json
import sys
import urllib.parse
from pathlib import Path


def uri_to_path(uri: str) -> Path:
    parsed = urllib.parse.urlparse(uri)
    return Path(urllib.parse.unquote(parsed.path))


def path_to_uri(path: Path) -> str:
    return Path(path).resolve().as_uri()


def find_game_root(file_path: Path) -> Path | None:
    curr = file_path.parent if file_path.is_file() else file_path
    while curr != curr.parent:
        if (curr / "world").is_dir() and (curr / "dialogue").is_dir():
            return curr
        curr = curr.parent
    return None


def extract_object_at_position(file_path: Path, line: int, character: int) -> str | None:
    if not file_path.exists():
        return None

    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    if line < 0 or line >= len(lines):
        return None

    line_text = lines[line]
    if character < 0 or character > len(line_text):
        return None

    def is_obj_char(c: str) -> bool:
        return c.isalnum() or c in ("-", "_")

    start = character
    while start > 0 and is_obj_char(line_text[start - 1]):
        start -= 1

    end = character
    while end < len(line_text) and is_obj_char(line_text[end]):
        end += 1

    token = line_text[start:end].strip()
    if not token or token == "objects":
        return None

    prefix = line_text[:start].strip()
    if prefix == "" or prefix.endswith(("-", ":")):
        return token

    return token


def find_definitions(game_root: Path, object_name: str) -> list[dict]:
    locations = []
    go_path = game_root / "world" / "game_objects" / f"{object_name}.yaml"
    ink_path = game_root / "dialogue" / f"{object_name}.ink"

    if go_path.is_file():
        locations.append({
            "uri": path_to_uri(go_path),
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 0},
            },
        })

    if ink_path.is_file():
        locations.append({
            "uri": path_to_uri(ink_path),
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 0},
            },
        })

    return locations


class WireframerLS:
    def __init__(self):
        self.documents = {}

    def send_response(self, response: dict):
        body = json.dumps(response, separators=(",", ":"))
        header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
        sys.stdout.write(header + body)
        sys.stdout.flush()

    def handle_request(self, request: dict):
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            self.send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "capabilities": {
                        "textDocumentSync": 1,
                        "definitionProvider": True,
                    }
                },
            })
        elif method == "textDocument/didOpen":
            doc = params.get("textDocument", {})
            uri = doc.get("uri")
            if uri:
                self.documents[uri] = doc.get("text", "")
        elif method == "textDocument/didChange":
            doc = params.get("textDocument", {})
            uri = doc.get("uri")
            changes = params.get("contentChanges", [])
            if uri and changes:
                self.documents[uri] = changes[-1].get("text", "")
        elif method == "textDocument/definition":
            doc_uri = params.get("textDocument", {}).get("uri", "")
            position = params.get("position", {})
            line = position.get("line", 0)
            character = position.get("character", 0)

            file_path = uri_to_path(doc_uri)
            game_root = find_game_root(file_path)

            locations = []
            if game_root:
                obj_name = extract_object_at_position(file_path, line, character)
                if obj_name:
                    locations = find_definitions(game_root, obj_name)

            self.send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": locations,
            })
        elif method == "shutdown":
            self.send_response({"jsonrpc": "2.0", "id": req_id, "result": None})
        elif method == "exit":
            sys.exit(0)
        else:
            if req_id is not None:
                self.send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": None,
                })

    def run(self):
        buffer = b""
        stdin = sys.stdin.buffer
        while True:
            chunk = stdin.read(1)
            if not chunk:
                break
            buffer += chunk
            while b"\r\n\r\n" in buffer:
                header_part, rest = buffer.split(b"\r\n\r\n", 1)
                content_length = None
                for line in header_part.decode("utf-8", errors="replace").split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":")[1].strip())
                        break

                if content_length is not None:
                    if len(rest) >= content_length:
                        body = rest[:content_length]
                        buffer = rest[content_length:]
                        try:
                            request = json.loads(body.decode("utf-8"))
                            self.handle_request(request)
                        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError):
                            pass
                    else:
                        break
                else:
                    buffer = rest


if __name__ == "__main__":
    server = WireframerLS()
    server.run()
