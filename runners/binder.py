from typing import Any


def resolve_path(path: str) -> str:
    roots = {
        "player",
        "rooms",
        "items",
        "quests",
        "variables",
        "game_objects",
        "global",
    }
    first = path.split(".")[0]
    if first in roots:
        return path
    return f"game_objects.{path}"


class Binder:
    def __init__(self, bindings):
        self.bindings = bindings

    def apply(self, value: dict[Any, Any] | list[str] | str) -> Any:
        """Recursively substitute $variables in strings.
        bindings is a dict like:
            {"self": "bob", "location": "town"}
        Convention: all bindings begin with a `$`.
        """

        if isinstance(value, dict):
            return {key: self.apply(val) for key, val in value.items()}

        if isinstance(value, list):
            return [self.apply(item) for item in value]

        if isinstance(value, str):
            print(value)
            value = resolve_path(value)
            print(value)
            for name, replacement in self.bindings.items():
                value = value.replace(f"${name}", replacement)
            print(value)
            return value

        # ints, bools, None, etc.
        return value
