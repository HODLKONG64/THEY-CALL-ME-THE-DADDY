from __future__ import annotations

from pathlib import Path


def test_engine_file_starts_without_utf8_bom_and_has_future_import_on_first_non_empty_line():
    path = Path("src/the_daddy/engine.py")
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    first_non_empty = next(
        (line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()),
        "",
    )
    assert first_non_empty == "from __future__ import annotations"
