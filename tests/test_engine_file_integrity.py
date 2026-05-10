from __future__ import annotations

from pathlib import Path


def test_engine_file_starts_without_utf8_bom_and_has_exact_first_line():
    path = Path("src/the_daddy/engine.py")
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "from __future__ import annotations"

