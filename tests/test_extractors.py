import inspect
from pathlib import Path

import pytest

from byte_mcp.errors import LimitExceededError
from byte_mcp.extractors import extract_file


def test_cp1252_text_does_not_get_misdecoded_as_utf16(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_bytes("café".encode("cp1252"))

    text, truncated, extractor = extract_file(path, 1_000)

    assert text == "café"
    assert truncated is False
    assert extractor == "text"


def test_extractor_has_defense_in_depth_input_limit(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_text("abcdef", encoding="utf-8")

    parameters = inspect.signature(extract_file).parameters
    if "max_input_bytes" not in parameters:
        pytest.fail("extract_file must enforce a max_input_bytes boundary")

    with pytest.raises(LimitExceededError, match="input limit"):
        extract_file(path, 1_000, max_input_bytes=5)
