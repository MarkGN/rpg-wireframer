"""
csv_to_ink.py

Converts a gym-leader dialogue CSV into one Ink (.ink) file per leader,
matching the hand-written format (see blaine.ink) used by the game's
dialogue system.

Usage:
    python3 gym_csv_to_ink.py gym_leader_dialogues.csv -o output_dir/
"""

import argparse
import csv
import sys
from pathlib import Path

# Columns expected in the CSV (order doesn't matter, header names do)
REQUIRED_FIELDS = ["id", "challenge", "win", "badge", "tm", "post_victory", "lose"]

INK_TEMPLATE = """{{ has("$player.inventory", "{badge_item}"):
    -> post_victory
   - else:
    -> challenge
}}

== challenge
{challenge}
~ scenario("trainer")
-> END

== win
~ victory()
{win}
~ add("$player.inventory", "{badge_item}")
~ add("$player.inventory", "{tm_item}")
-> END

== lose
{lose}
~ defeat()
-> END

== post_victory
{post_victory}
-> END
"""


def unescape_field(value: str) -> str:
    """
    Fields in the source CSV use a literal backslash-n ("\\n") to indicate
    a line break within a single cell, rather than an embedded real newline.
    Convert those into actual newlines for the Ink output, and drop any
    surrounding whitespace.
    """
    if value is None:
        return ""
    return value.replace("\\n", "\n").strip()


def load_rows(csv_path: Path):
    with csv_path.open(newline="", encoding="utf-8") as f:
        # skipinitialspace handles the ", challenge, win, ..." header style
        # (a space after each comma in the source file).
        reader = csv.DictReader(f, skipinitialspace=True)

        # Normalize header whitespace just in case.
        reader.fieldnames = [name.strip() for name in reader.fieldnames]

        missing = set(REQUIRED_FIELDS) - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"CSV is missing required column(s): {', '.join(sorted(missing))}"
            )

        rows = []
        for i, row in enumerate(reader, start=2):  # start=2: header is line 1
            if not row.get("id", "").strip():
                continue  # skip blank rows
            rows.append({k: (v or "").strip() for k, v in row.items()})
        return rows


def row_to_ink(row: dict) -> str:
    badge_item = f"{row['badge'].strip()}_badge"
    tm_item = f"tm_{row['tm'].strip()}"

    return INK_TEMPLATE.format(
        badge_item=badge_item,
        tm_item=tm_item,
        challenge=unescape_field(row["challenge"]),
        win=unescape_field(row["win"]),
        lose=unescape_field(row["lose"]),
        post_victory=unescape_field(row["post_victory"]),
    )


def convert(csv_path: Path, out_dir: Path) -> list:
    rows = load_rows(csv_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for row in rows:
        leader_id = row["id"].strip().lower()
        out_path = out_dir / f"{leader_id}.ink"
        out_path.write_text(row_to_ink(row), encoding="utf-8")
        written.append(out_path)
    return written


def main():
    parser = argparse.ArgumentParser(description="Convert gym leader CSV to Ink files.")
    parser.add_argument("csv_file", type=Path, help="Path to the input CSV file")
    parser.add_argument(
        "-o", "--out-dir", type=Path, default=Path("."),
        help="Directory to write the .ink files into (default: current directory)",
    )
    args = parser.parse_args()

    if not args.csv_file.exists():
        print(f"Error: {args.csv_file} does not exist", file=sys.stderr)
        sys.exit(1)

    written = convert(args.csv_file, args.out_dir)
    print(f"Wrote {len(written)} file(s) to {args.out_dir}/:")
    for path in written:
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
