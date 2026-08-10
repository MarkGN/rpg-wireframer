import textwrap
from pathlib import Path

from export.export_rooms_to_dot import export_rooms_to_dot


def test_export_rooms_to_dot_generates_graph(tmp_path: Path) -> None:
    game_dir = tmp_path / "game"
    (game_dir / "world" / "rooms").mkdir(parents=True)
    (game_dir / "world" / "game.yaml").write_text(
        textwrap.dedent(
            """
            player: hero
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (game_dir / "world" / "rooms" / "start.yaml").write_text(
        textwrap.dedent(
            """
            name: Start
            exits:
              - middle
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (game_dir / "world" / "rooms" / "middle.yaml").write_text(
        textwrap.dedent(
            """
            name: Middle
            exits:
              start: start
              end: end
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (game_dir / "world" / "rooms" / "end.yaml").write_text(
        textwrap.dedent(
            """
            name: End
            exits: []
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    output = game_dir / "rooms.dot"
    export_rooms_to_dot(game_dir, output)

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "digraph rooms" in content
    assert (
        '"start" -> "middle" [dir=both];' in content
        or '"middle" -> "start" [dir=both];' in content
    )
    assert '"middle" -> "end";' in content
