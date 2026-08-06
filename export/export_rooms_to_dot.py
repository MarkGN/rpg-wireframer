from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def parse_exits(exits: Any) -> list[str]:
    if exits is None:
        return []
    if isinstance(exits, dict):
        targets: list[str] = []
        for target in exits.values():
            if isinstance(target, str):
                targets.append(target)
            elif isinstance(target, dict):
                room = target.get("room")
                if not isinstance(room, str):
                    raise ValueError(
                        f"Exit object must contain a string room field, got {target!r}"
                    )
                targets.append(room)
            else:
                raise ValueError(
                    f"Invalid exit value {target!r}; expected string or mapping"
                )
        return targets
    if isinstance(exits, list):
        targets: list[str] = []
        for target in exits:
            if not isinstance(target, str):
                raise ValueError(
                    f"Invalid exit target {target!r}; expected room handle string"
                )
            targets.append(target)
        return targets
    raise ValueError(f"Invalid exits value {exits!r}; expected list or mapping")


def quote_node(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def load_rooms(game_path: Path) -> dict[str, dict[str, Any]]:
    rooms_dir = game_path / "world" / "rooms"
    rooms: dict[str, dict[str, Any]] = {}
    for path in sorted(rooms_dir.rglob("*.yaml")):
        room_id = path.stem
        rooms[room_id] = load_yaml(path)
    return rooms


def build_edges(rooms: dict[str, dict[str, Any]]) -> dict[tuple[str, str], str]:
    edges: dict[tuple[str, str], str] = {}
    directed_edges = {
        (src, target)
        for src, room in rooms.items()
        for target in parse_exits(room.get("exits", []))
    }

    for src, target in sorted(directed_edges):
        if target not in rooms:
            raise ValueError(f"Room '{src}' links to unknown target '{target}'")

    seen: set[tuple[str, str]] = set()
    for src, target in sorted(directed_edges):
        if (src, target) in seen:
            continue
        if src != target and (target, src) in directed_edges:
            if (target, src) in seen:
                continue
            edges[(src, target)] = "both"
            seen.add((src, target))
            seen.add((target, src))
        else:
            edges[(src, target)] = "directed"
            seen.add((src, target))
    return edges


def render_dot(
    rooms: dict[str, dict[str, Any]], edges: dict[tuple[str, str], str]
) -> str:
    lines = ["digraph rooms {", "  rankdir=LR;", "  node [shape=box];", ""]
    for room_id in sorted(rooms):
        lines.append(f"  {quote_node(room_id)};")
    if rooms:
        lines.append("")
    for (src, target), edge_type in edges.items():
        if src == target:
            lines.append(f"  {quote_node(src)} -> {quote_node(target)};")
        elif edge_type == "both":
            lines.append(f"  {quote_node(src)} -> {quote_node(target)} [dir=both];")
        else:
            lines.append(f"  {quote_node(src)} -> {quote_node(target)};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def export_rooms_to_dot(game_path: Path, output_path: Path) -> None:
    rooms = load_rooms(game_path)
    edges = build_edges(rooms)
    dot = render_dot(rooms, edges)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dot, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export world room connectivity to Graphviz DOT format."
    )
    parser.add_argument("game", help="Path to the game directory")
    parser.add_argument(
        "--output",
        default="rooms.dot",
        help="Output DOT file path relative to game directory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    game_path = Path(args.game)
    output_path = game_path / args.output
    export_rooms_to_dot(game_path, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
