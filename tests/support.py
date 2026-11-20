"""Shared fixtures and helpers for the test suite."""

from __future__ import annotations

import csv
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "examples" / "pilot"
DATA = ROOT / "data"


def copy_pilot(destination: Path) -> Path:
    target = destination / "pilot"
    shutil.copytree(PILOT, target)
    return target


def write_csv(path: Path, rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class TempProject:
    """A throwaway copy of the pilot example for mutation tests."""

    def __init__(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = copy_pilot(Path(self._dir.name))

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *exc: object) -> None:
        self._dir.cleanup()
