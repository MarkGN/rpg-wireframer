from __future__ import annotations

from pathlib import Path

from validate.ink_analyser import (
    INTERNAL_TARGETS,
    _is_internal_target,
    analyze_ink_file,
)


def validate_dialogues(game_path: Path | str) -> None:
    game_path = Path(game_path)
    dialogue_dir = game_path / "dialogue"
    if not dialogue_dir.exists() or not dialogue_dir.is_dir():
        raise ValueError(f"Dialogue directory not found: {dialogue_dir}")

    ink_paths = sorted(dialogue_dir.rglob("*.ink"))
    if not ink_paths:
        raise ValueError(f"No Ink files found in {dialogue_dir}")

    for ink_path in ink_paths:
        if ink_path.name == "globals.ink":
            continue

        ink_filename = ink_path.name
        graph, _, _ = analyze_ink_file(ink_filename, dialogue_dir, game_path)

        all_knots = {name for name in graph if name != "__root__"}
        visited: set[str] = set()
        stack = ["__root__"]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for successor in graph.get(current, []):
                if successor not in visited:
                    stack.append(successor)
        reachable = visited

        unreachable = sorted(all_knots - reachable)
        if unreachable:
            raise ValueError(
                f"{ink_path}: unreachable knots/stitches: {', '.join(unreachable)}"
            )

        # validate target existence after scenario edges are added
        target_errors: list[str] = []
        for origin, successors in graph.items():
            if origin == "__root__":
                continue
            for target in successors:
                if target not in all_knots and target not in INTERNAL_TARGETS and not _is_internal_target(target, all_knots):
                    target_errors.append(
                        f"{ink_path}: missing divert target '{target}' in knot '{origin}'"
                    )
        for target in graph["__root__"]:
            if target not in all_knots and target not in INTERNAL_TARGETS and not _is_internal_target(target, all_knots):
                target_errors.append(
                    f"{ink_path}: missing divert target '{target}' in root flow"
                )
        if target_errors:
            raise ValueError("\n".join(target_errors))



if __name__ == "__main__":
    import sys

    validate_dialogues(Path(sys.argv[1]))
