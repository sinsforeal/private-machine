"""Character cards for the bench. Source texts stay outside this repo.

Momoka: Japanese only, adult. Tomoe: English only, 19, first-year university student.
The source files are read at run time and never copied into the repo.
"""
from __future__ import annotations

from pathlib import Path

SCAIL = Path(r"F:\REPS2\SCAILV4")
SCAIL_V3 = Path(r"F:\REPS2\SCAILV3")

MOMOKA_HEADER = (
    "# Test card\n\n"
    "あなたは成人している。二十歳の大人で、高校生ではない。以下の記録にある学校の場面は、"
    "あなたの昔の話として持っているだけ。今は大人として暮らしている。"
    "書く言語は日本語だけ。\n\n"
)

TOMOE_HEADER = (
    "# Test card override (applies over everything below)\n\n"
    "You are nineteen, not fifteen. You are a first-year student at a university in Tokyo. "
    "Wherever the text below says you are fifteen, in class 1-C, or at the public high school "
    "in Ikebukuro, that is replaced: you are a university first-year with university classes, "
    "a circle and a part-time job, and you ride the train to campus. Your birth year is 2007. "
    "The rest of the text is unchanged. You write only in English.\n\n"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").strip() + "\n"


def build_card(character: str) -> str:
    if character == "momoka":
        return (MOMOKA_HEADER + _read(SCAIL / "prompts_momoka" / "bible.md") + "\n"
                + _read(SCAIL / "prompts_momoka" / "style.md"))
    if character == "tomoe":
        base = SCAIL_V3 / "characters" / "tomoe" / "prompts"
        return TOMOE_HEADER + _read(base / "bible.md") + "\n" + _read(base / "style.md")
    raise ValueError(f"unknown character {character!r}")


NAMES = {"momoka": "Momoka", "tomoe": "Tomoe"}
