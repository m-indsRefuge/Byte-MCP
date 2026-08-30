import pytest

from byte_mcp.errors import WriteConflictError, WriteLimitError, WritePatchError, WritePolicyError
from byte_mcp.write.manifest import build_manifest
from byte_mcp.write.operations import (
    OperationKind,
    TextEdit,
    apply_text_edits,
    parse_operation,
)


def _operation(kind: str, **values: object):
    return parse_operation({"kind": kind, **values})


def test_operation_schemas_accept_only_their_required_fields() -> None:
    assert (
        _operation("create_directory", path="projects/demo/dir").kind
        is OperationKind.CREATE_DIRECTORY
    )
    assert (
        _operation("create_text_file", path="projects/demo/a.txt", content="hello").content
        == "hello"
    )
    assert (
        _operation(
            "replace_text_file", path="projects/demo/a.txt", content="new", expected_sha256="a" * 64
        ).expected_sha256
        == "a" * 64
    )
    assert _operation(
        "patch_text_file",
        path="projects/demo/a.txt",
        expected_sha256="b" * 64,
        edits=[{"expected_text": "old", "replacement_text": "new"}],
    ).edits == (TextEdit("old", "new"),)
    assert _operation("move", path="projects/demo/a", destination="projects/demo/b").destination
    assert (
        _operation(
            "move",
            path="projects/demo/a",
            destination="projects/demo/b",
            expected_sha256="c" * 64,
        ).expected_sha256
        == "c" * 64
    )
    assert _operation("recover_delete", path="projects/demo/a").path
    assert (
        _operation(
            "recover_delete", path="projects/demo/a", expected_sha256="d" * 64
        ).expected_sha256
        == "d" * 64
    )
    assert _operation(
        "restore_recovery_item", recovery_id="RCV-0123456789abcdef", destination="projects/demo/a"
    ).recovery_id


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "create_directory", "path": "projects/demo/a", "content": "no"},
        {"kind": "create_text_file", "path": "projects/demo/a", "content": "x", "other": "no"},
        {"kind": "create_text_file", "path": "projects/demo/a", "content": "bad\x00"},
        {
            "kind": "replace_text_file",
            "path": "projects/demo/a",
            "content": "x",
            "expected_sha256": "bad",
        },
        {
            "kind": "restore_recovery_item",
            "recovery_id": "RCV-bad!",
            "destination": "projects/demo/a",
        },
    ],
)
def test_operation_schema_rejects_unknown_or_malformed_values(payload: dict[str, object]) -> None:
    with pytest.raises(WritePolicyError):
        parse_operation(payload)


def test_operation_schema_enforces_file_and_patch_limits(write_policy_file) -> None:
    from byte_mcp.write.policy import WritePolicy

    policy = WritePolicy.load(write_policy_file)
    with pytest.raises(WriteLimitError):
        parse_operation(
            {"kind": "create_text_file", "path": "projects/demo/a", "content": "x" * 1_000_001},
            policy,
        )
    with pytest.raises(WriteLimitError):
        parse_operation(
            {
                "kind": "patch_text_file",
                "path": "projects/demo/a",
                "expected_sha256": "a" * 64,
                "edits": [{"expected_text": "x" * 500_001, "replacement_text": "y" * 500_000}],
            },
            policy,
        )


def test_patch_rejects_ambiguous_fragment() -> None:
    source = "x = 1\nx = 1\n"
    edit = TextEdit(expected_text="x = 1", replacement_text="x = 2")
    with pytest.raises(WritePatchError, match="exactly once"):
        apply_text_edits(source, (edit,))


def test_patch_rejects_overlapping_fragments_and_applies_in_reverse_order() -> None:
    with pytest.raises(WritePatchError, match="overlap"):
        apply_text_edits("abcdef", (TextEdit("abc", "X"), TextEdit("bcd", "Y")))
    assert (
        apply_text_edits("first second", (TextEdit("first", "1"), TextEdit("second", "2"))) == "1 2"
    )


def test_manifest_orders_dependencies_and_hashes_full_in_memory_request(write_policy_file) -> None:
    from byte_mcp.write.policy import WritePolicy

    policy = WritePolicy.load(write_policy_file)
    manifest = build_manifest(
        (
            _operation(
                "create_text_file", path="projects/demo/dir/a.txt", content="secret-ish body"
            ),
            _operation("create_directory", path="projects/demo"),
            _operation("create_directory", path="projects/demo/dir"),
        ),
        policy,
    )
    assert manifest.project == "demo"
    assert [operation.kind for operation in manifest.ordered_operations] == [
        OperationKind.CREATE_DIRECTORY,
        OperationKind.CREATE_DIRECTORY,
        OperationKind.CREATE_TEXT_FILE,
    ]
    changed = build_manifest(
        (
            _operation("create_directory", path="projects/demo"),
            _operation("create_directory", path="projects/demo/dir"),
            _operation(
                "create_text_file", path="projects/demo/dir/a.txt", content="different body"
            ),
        ),
        policy,
    )
    assert manifest.manifest_sha256 != changed.manifest_sha256


@pytest.mark.parametrize(
    "operations",
    [
        (
            _operation("create_directory", path="projects/demo"),
            _operation("create_directory", path="projects/demo"),
        ),
        (
            _operation("move", path="projects/demo/a", destination="projects/demo/b"),
            _operation("move", path="projects/demo/b", destination="projects/demo/a"),
        ),
        (
            _operation("recover_delete", path="projects/demo/dir"),
            _operation("create_text_file", path="projects/demo/dir/a.txt", content="x"),
        ),
        (
            _operation("create_text_file", path="projects/demo/a", content="x"),
            _operation("move", path="projects/demo/b", destination="projects/demo/a"),
        ),
        (
            _operation("create_directory", path="projects/demo"),
            _operation("create_directory", path="projects/other"),
        ),
        (_operation("move", path="projects/demo/a", destination="projects/other/a"),),
        (_operation("create_text_file", path="projects/demo/missing/a.txt", content="x"),),
    ],
)
def test_manifest_rejects_conflicting_or_cross_project_operations(
    write_policy_file, operations
) -> None:
    from byte_mcp.write.policy import WritePolicy

    with pytest.raises((WriteConflictError, WritePolicyError)):
        build_manifest(operations, WritePolicy.load(write_policy_file))


def test_manifest_rejects_operation_count_overflow(write_policy_file) -> None:
    from byte_mcp.write.policy import WritePolicy

    policy = WritePolicy.load(write_policy_file)
    operations = tuple(
        _operation("create_directory", path=f"projects/demo/{index}") for index in range(201)
    )
    with pytest.raises(WriteLimitError):
        build_manifest(operations, policy)
