#!/usr/bin/env python3
import json
import re
import sys
import urllib.parse
from pathlib import Path

import yaml


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


def extract_token_at_position(
    file_path: Path, line: int, character: int
) -> str | None:
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


def read_lines(file_path: Path) -> list[str] | None:
    try:
        return file_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def section_at_position(
    lines: list[str], line: int
) -> tuple[str, int, int] | None:
    section = None
    section_indent = 0
    section_line = 0
    for current_line_number, current_line in enumerate(lines[: line + 1]):
        match = re.match(r"^(\s*)(exits|objects):\s*(?:#.*)?$", current_line)
        if match:
            section = match.group(2)
            section_indent = len(match.group(1))
            section_line = current_line_number
            continue

        if current_line.strip() and len(current_line) - len(current_line.lstrip()) <= section_indent:
            section = None

    if section is None:
        return None
    return section, section_indent, section_line


def extract_room_reference_at_position(
    file_path: Path, line: int, character: int
) -> str | None:
    lines = read_lines(file_path)
    if lines is None or line < 0 or line >= len(lines):
        return None

    section = section_at_position(lines, line)
    if section is None or section[0] != "exits":
        return None

    token = extract_token_at_position(file_path, line, character)
    if token is None:
        return None

    match = re.match(r"^\s*[^:#]+:\s*([^#\s]+)", lines[line])
    if match:
        return match.group(1)
    return token


def extract_object_reference_at_position(
    file_path: Path, line: int, character: int
) -> tuple[str, str | None] | None:
    lines = read_lines(file_path)
    if lines is None or line < 0 or line >= len(lines):
        return None

    section = section_at_position(lines, line)
    if section is None or section[0] != "objects":
        return None

    section_line = section[2]
    current_object = None
    current_ink = None
    for current_line in lines[section_line + 1 : line + 1]:
        entry = re.match(
            r"^\s*-\s*(?:([A-Za-z0-9_-]+)\s*:|([A-Za-z0-9_.-]+))",
            current_line,
        )
        if entry:
            current_object = entry.group(1) or entry.group(2)
            current_ink = None
            continue

        if current_object is not None:
            ink = re.match(r"^\s+ink:\s*([^#\s]+)", current_line)
            if ink:
                current_ink = ink.group(1)

    if current_object is None:
        return None
    return current_object, current_ink


def find_named_file(directory: Path, name: str) -> Path | None:
    requested = Path(name)
    candidates = [directory / requested]
    if requested.suffix not in (".yaml", ".yml"):
        candidates.extend(
            [directory / f"{name}.yaml", directory / f"{name}.yml"]
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    filename = requested.name
    for candidate in directory.rglob("*"):
        if candidate.is_file() and candidate.name in {
            filename,
            f"{filename}.yaml",
            f"{filename}.yml",
        }:
            return candidate
    return None


def find_ink_file(directory: Path, name: str) -> Path | None:
    requested = Path(name)
    if requested.suffix != ".ink":
        requested = requested.with_suffix(".ink")

    direct = directory / requested
    if direct.is_file():
        return direct

    for candidate in directory.rglob(requested.name):
        if candidate.is_file():
            return candidate
    return None


def object_ink_name(object_path: Path, inline_ink: str | None) -> str:
    if inline_ink:
        return inline_ink

    try:
        with object_path.open(encoding="utf-8") as stream:
            object_data = yaml.safe_load(stream) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        object_data = {}

    override = object_data.get("ink")
    return override if isinstance(override, str) and override else object_path.stem


def find_definitions(
    game_root: Path,
    name: str,
    reference_type: str = "object",
    inline_ink: str | None = None,
) -> list[dict]:
    locations = []
    if reference_type == "room":
        target = find_named_file(game_root / "world" / "rooms", name)
        targets = [target] if target else []
    else:
        target = find_named_file(game_root / "world" / "objects", name)
        targets = [target] if target else []

    for go_path in targets:
        if go_path is None:
            continue
        locations.append({
            "uri": path_to_uri(go_path),
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 0},
            },
        })

    if reference_type == "object":
        ink_name = (
            object_ink_name(target, inline_ink)
            if target is not None
            else (inline_ink or name)
        )
        ink_path = find_ink_file(game_root / "dialogue", ink_name)
        if ink_path is not None:
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
                room_name = extract_room_reference_at_position(
                    file_path, line, character
                )
                if room_name:
                    locations = find_definitions(game_root, room_name, "room")
                else:
                    object_reference = extract_object_reference_at_position(
                        file_path, line, character
                    )
                    if object_reference:
                        object_name, inline_ink = object_reference
                        locations = find_definitions(
                            game_root, object_name, "object", inline_ink
                        )
                    elif (
                        file_path.suffix == ".ink"
                        and game_root / "dialogue" in file_path.parents
                        and file_path.name != "globals.ink"
                    ):
                        locations = find_definitions(
                            game_root, file_path.stem, "object"
                        )

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
