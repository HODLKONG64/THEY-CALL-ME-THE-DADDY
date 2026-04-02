from __future__ import annotations

from pathlib import Path
from rich.console import Console

console = Console()


def write_local_summary(text: str, base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "last_run_summary.txt").write_text(text, encoding="utf-8")
