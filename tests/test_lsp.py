import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


class TestLSP(unittest.TestCase):
    def test_goto_definition(self):
        lsp_path = ROOT_DIR / "tools" / "lsp.py"
        proc = subprocess.Popen(
            [sys.executable, str(lsp_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        def send(msg):
            body = json.dumps(msg)
            req = f"Content-Length: {len(body)}\r\n\r\n{body}".encode()
            proc.stdin.write(req)
            proc.stdin.flush()

        def read():
            line = proc.stdout.readline().decode("utf-8")
            length = int(line.split(":")[1].strip())
            proc.stdout.readline()  # blank line
            return json.loads(proc.stdout.read(length).decode("utf-8"))

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        init_res = read()
        self.assertTrue(init_res["result"]["capabilities"]["definitionProvider"])

        room_file = ROOT_DIR / "games/demos/pokemon/world/rooms/pallet/red_room.yaml"
        send({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "textDocument/definition",
            "params": {
                "textDocument": {"uri": room_file.as_uri()},
                "position": {"line": 6, "character": 5},
            },
        })
        def_res = read()
        uris = [item["uri"] for item in def_res["result"]]

        expected_go = (ROOT_DIR / "games/demos/pokemon/world/objects/red.yaml").as_uri()
        expected_ink = (ROOT_DIR / "games/demos/pokemon/dialogue/red.ink").as_uri()

        self.assertIn(expected_go, uris)
        self.assertIn(expected_ink, uris)

        send({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}})
        read()
        send({"jsonrpc": "2.0", "method": "exit", "params": {}})
        proc.stdin.close()
        proc.stdout.close()
        proc.wait()


if __name__ == "__main__":
    unittest.main()
