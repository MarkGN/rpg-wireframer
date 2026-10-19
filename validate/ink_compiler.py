from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from yaml_utils import load_yaml

_COMPILE_CACHE: dict[
    Path, tuple[tuple[tuple[str, int, int], ...], tuple[int, int]]
] = {}
_COMPILE_ERROR_CACHE: dict[
    Path,
    tuple[tuple[tuple[str, int, int], ...], str, tuple[int, int] | None],
] = {}


def _compile_dependencies(
    ink_path: Path, globals_path: Path, custom_externals_path: Path
) -> list[Path]:
    dependencies = [ink_path]
    if globals_path.exists():
        dependencies.append(globals_path)
    if custom_externals_path.exists():
        dependencies.append(custom_externals_path)
    return dependencies


def _dependency_signature(
    dependencies: list[Path],
) -> tuple[tuple[str, int, int], ...]:
    signature = []
    for path in dependencies:
        stat = path.stat()
        signature.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def find_ink_path(ink_filename: str, dialogue_dir: Path) -> Path | None:
    candidate = dialogue_dir / ink_filename
    if candidate.exists():
        return candidate

    target_name = Path(ink_filename).name
    for path in sorted(dialogue_dir.rglob("*.ink")):
        if path.name == target_name:
            return path

    return None


def load_custom_externals_definitions(dialogue_dir: Path) -> dict[str, int]:
    custom_path = dialogue_dir / "custom_externals.yaml"
    if not custom_path.exists():
        return {}

    raw = load_yaml(custom_path)

    if not isinstance(raw, dict):
        raise TypeError(f"Expected mapping in {custom_path}, got {type(raw).__name__}")

    custom_externals: dict[str, int] = {}
    for name, spec in raw.items():
        if not isinstance(name, str):
            raise TypeError(f"Invalid custom external name {name!r} in {custom_path}")
        if isinstance(spec, dict) and "args" in spec:
            arg_count = spec["args"]
        elif isinstance(spec, int):
            arg_count = spec
        else:
            raise ValueError(
                f"Invalid custom external spec for {name!r} in {custom_path}: {spec!r}"
            )
        if not isinstance(arg_count, int) or arg_count < 0:
            raise ValueError(
                f"Invalid arg count for {name!r} in {custom_path}: {arg_count!r}"
            )
        custom_externals[name] = arg_count
    return custom_externals


def ink_json_path(ink_filename: str, dialogue_dir: Path) -> Path:
    """Return a fresh compiled Ink JSON file, compiling only stale inputs."""
    ink_path = find_ink_path(ink_filename, dialogue_dir)
    if ink_path is None:
        raise ValueError(f"Dialogue file not found: {dialogue_dir / ink_filename}")

    json_path = ink_path.with_suffix(".ink.json")
    globals_path = dialogue_dir / "globals.ink"
    custom_externals_path = dialogue_dir / "custom_externals.yaml"
    dependencies = _compile_dependencies(ink_path, globals_path, custom_externals_path)
    signature = _dependency_signature(dependencies)
    cache_key = ink_path.resolve()

    try:
        json_stat = json_path.stat()
    except FileNotFoundError:
        json_stat = None
    json_signature = (
        (json_stat.st_mtime_ns, json_stat.st_size) if json_stat is not None else None
    )
    cached_error = _COMPILE_ERROR_CACHE.get(cache_key)
    if (
        cached_error is not None
        and cached_error[0] == signature
        and cached_error[2] == json_signature
    ):
        raise ValueError(cached_error[1])

    if json_stat is not None:
        cached = _COMPILE_CACHE.get(cache_key)
        if cached == (signature, json_signature):
            return json_path

        newest_dependency = max(mtime for _, mtime, _ in signature)
        if json_stat.st_mtime_ns >= newest_dependency:
            _COMPILE_CACHE[cache_key] = (signature, json_signature)
            _COMPILE_ERROR_CACHE.pop(cache_key, None)
            return json_path

    custom_externals = load_custom_externals_definitions(dialogue_dir)
    source_path = ink_path
    temp_path = None

    if globals_path.exists() or custom_externals:
        include_path = (
            os.path.relpath(globals_path, start=ink_path.parent)
            if globals_path.exists()
            else None
        )
        with tempfile.NamedTemporaryFile(
            dir=ink_path.parent,
            suffix=".ink",
            delete=False,
            mode="w",
            encoding="utf-8",
        ) as temp_file:
            try:
                if include_path is not None:
                    temp_file.write(f"INCLUDE {include_path}\n")
                if custom_externals:
                    for name, arg_count in custom_externals.items():
                        args = ", ".join(f"arg{i}" for i in range(arg_count))
                        temp_file.write(f"EXTERNAL {name}({args})\n")
                temp_file.write(ink_path.read_text(encoding="utf-8"))
                temp_file.close()
                temp_path = Path(temp_file.name)
                source_path = temp_path

                result = subprocess.run(
                    ["inklecate", "-o", str(json_path), str(source_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
    else:
        result = subprocess.run(
            ["inklecate", "-o", str(json_path), str(source_path)],
            capture_output=True,
            text=True,
            check=False,
        )

    if result.returncode != 0:
        err_output = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
        match = re.search(r"line\s+(\d+)", err_output, re.IGNORECASE)
        line_no = int(match.group(1)) if match else 1
        ink_path_obj = find_ink_path(ink_filename, dialogue_dir)
        bad_code = ""
        if ink_path_obj and ink_path_obj.exists():
            lines = ink_path_obj.read_text(encoding="utf-8").splitlines()
            if 1 <= line_no <= len(lines):
                bad_code = lines[line_no - 1].strip()

        error_message = (
            f"Error compiling Ink file '{ink_filename}' at line {line_no}:\n"
            f"  Line {line_no}: {bad_code}\n"
            f"Diagnostics: {err_output}"
        )
        try:
            json_stat = json_path.stat()
        except FileNotFoundError:
            failed_json_signature = None
        else:
            failed_json_signature = (json_stat.st_mtime_ns, json_stat.st_size)
        _COMPILE_ERROR_CACHE[cache_key] = (
            signature,
            error_message,
            failed_json_signature,
        )
        raise ValueError(error_message)

    _COMPILE_ERROR_CACHE.pop(cache_key, None)
    try:
        json_stat = json_path.stat()
    except FileNotFoundError:
        _COMPILE_CACHE.pop(cache_key, None)
    else:
        _COMPILE_CACHE[cache_key] = (
            signature,
            (json_stat.st_mtime_ns, json_stat.st_size),
        )

    return json_path
