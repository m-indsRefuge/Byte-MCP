from __future__ import annotations

from pathlib import Path

import pytest
from byte_mcp.write.staging import (
    StagingStore,
    TextFileProfile,
    directory_manifest,
    encode_with_profile,
    read_utf8_profile,
)

from byte_mcp.errors import WriteIntegrityError, WriteLimitError, WritePathError


def test_utf8_profiles_preserve_bom_and_detect_single_newline_convention() -> None:
    text, profile = read_utf8_profile(b"alpha\r\nbeta\r\n")
    assert text == "alpha\r\nbeta\r\n"
    assert profile == TextFileProfile(has_utf8_bom=False, newline="\r\n")

    bom_text, bom_profile = read_utf8_profile(b"\xef\xbb\xbfalpha\nbeta\n")
    assert bom_text == "alpha\nbeta\n"
    assert bom_profile == TextFileProfile(has_utf8_bom=True, newline="\n")

    _, mixed = read_utf8_profile(b"alpha\r\nbeta\ngamma\r")
    assert mixed.newline is None


@pytest.mark.parametrize("data", [b"\xff\xfe", b"alpha\x00beta"])
def test_utf8_profile_rejects_invalid_or_nul_content(data: bytes) -> None:
    with pytest.raises(WriteIntegrityError):
        read_utf8_profile(data)


def test_encode_with_profile_normalizes_only_when_source_has_one_newline_style() -> None:
    crlf = TextFileProfile(has_utf8_bom=True, newline="\r\n")
    assert encode_with_profile("a\nb\rc\r\nd", crlf) == b"\xef\xbb\xbfa\r\nb\r\nc\r\nd"

    mixed = TextFileProfile(has_utf8_bom=False, newline=None)
    assert encode_with_profile("a\nb\rc\r\nd", mixed) == b"a\nb\rc\r\nd"


def test_staging_store_binds_blob_identity_and_detects_tampering(write_env) -> None:
    store = StagingStore(write_env.state_dir)
    staged = store.stage_bytes("TX-0123456789abcdef", 2, b"hello")

    assert staged.blob_id == "OP-0002"
    assert staged.byte_count == 5
    assert store.read_bytes(staged) == b"hello"
    store.verify(staged)

    staged.absolute.write_bytes(b"tampered")
    with pytest.raises(WriteIntegrityError, match="staged"):
        store.verify(staged)


def test_directory_manifest_is_deterministic_and_text_safe(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "B").mkdir(parents=True)
    (root / "a").mkdir()
    (root / "B" / "z.txt").write_text("z", encoding="utf-8")
    (root / "a" / "x.txt").write_text("x", encoding="utf-8")

    first = directory_manifest(root, max_entries=10, max_bytes=100, require_text=True)
    second = directory_manifest(root, max_entries=10, max_bytes=100, require_text=True)

    assert first.digest == second.digest
    assert first.entry_count == 4
    assert first.byte_count == 2
    assert [row.relative_path for row in first.entries] == ["a", "a/x.txt", "B", "B/z.txt"]


def test_directory_manifest_rejects_secret_binary_linked_and_over_limit_entries(
    tmp_path: Path,
) -> None:
    secret_root = tmp_path / "secret-tree"
    secret_root.mkdir()
    (secret_root / ".env").write_text("TOKEN=x", encoding="utf-8")
    with pytest.raises(WritePathError):
        directory_manifest(secret_root, max_entries=10, max_bytes=100, require_text=True)

    binary_root = tmp_path / "binary-tree"
    binary_root.mkdir()
    (binary_root / "bad.bin").write_bytes(b"\xff\xfe")
    with pytest.raises(WriteIntegrityError):
        directory_manifest(binary_root, max_entries=10, max_bytes=100, require_text=True)

    linked_root = tmp_path / "linked-tree"
    linked_root.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    linked = linked_root / "linked.txt"
    try:
        linked.symlink_to(target)
    except OSError:
        pass
    else:
        with pytest.raises(WritePathError):
            directory_manifest(linked_root, max_entries=10, max_bytes=100, require_text=True)

    hard_root = tmp_path / "hard-tree"
    hard_root.mkdir()
    original = hard_root / "original.txt"
    original.write_text("x", encoding="utf-8")
    hard = hard_root / "hard.txt"
    try:
        hard.hardlink_to(original)
    except OSError:
        pass
    else:
        with pytest.raises(WritePathError, match="hard link"):
            directory_manifest(hard_root, max_entries=10, max_bytes=100, require_text=True)

    limit_root = tmp_path / "limit-tree"
    limit_root.mkdir()
    (limit_root / "a.txt").write_text("12345", encoding="utf-8")
    with pytest.raises(WriteLimitError):
        directory_manifest(limit_root, max_entries=10, max_bytes=4, require_text=True)
    with pytest.raises(WriteLimitError):
        directory_manifest(limit_root, max_entries=0, max_bytes=100, require_text=True)
