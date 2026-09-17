import json
from pathlib import Path

import pytest

from byte_mcp import security
from byte_mcp.errors import OXRepositoryError, OXScopeError
from byte_mcp.ox import scope as scope_module
from byte_mcp.ox.models import OXReviewMode
from byte_mcp.ox.scope import OXScopeResolver


def _projects_with_repository(tmp_path: Path) -> tuple[Path, Path]:
    projects = tmp_path / "projects"
    repository = projects / "example"
    repository.mkdir(parents=True)
    return projects, repository


def test_repository_resolution_is_direct_child_and_hides_absolute_path(tmp_path: Path) -> None:
    projects, repository = _projects_with_repository(tmp_path)
    resolver = OXScopeResolver(projects)

    resolved = resolver.resolve_repository("example")

    assert resolved.alias == "example"
    assert resolved.path == repository.resolve()
    assert str(repository.resolve()) not in repr(resolved)


@pytest.mark.parametrize(
    "repository",
    (
        "",
        "   ",
        ".",
        "..",
        "/absolute",
        "nested/repository",
        r"nested\repository",
        "C:repository",
        "C:/repository",
        r"C:\repository",
        "bad\nname",
        "bad\x1fname",
    ),
)
def test_repository_resolution_rejects_non_direct_or_unsafe_aliases(
    tmp_path: Path,
    repository: str,
) -> None:
    projects, _ = _projects_with_repository(tmp_path)
    resolver = OXScopeResolver(projects)

    with pytest.raises(OXRepositoryError):
        resolver.resolve_repository(repository)


def test_repository_resolution_rejects_missing_and_non_directory_entries(tmp_path: Path) -> None:
    projects, _ = _projects_with_repository(tmp_path)
    (projects / "plain-file").write_text("not a repository", encoding="utf-8")
    resolver = OXScopeResolver(projects)

    with pytest.raises(OXRepositoryError):
        resolver.resolve_repository("missing")
    with pytest.raises(OXRepositoryError):
        resolver.resolve_repository("plain-file")


def test_repository_link_check_happens_before_candidate_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects, repository = _projects_with_repository(tmp_path)
    resolver = OXScopeResolver(projects)

    monkeypatch.setattr(
        scope_module,
        "is_link_or_junction",
        lambda path: path == repository,
    )

    def fail_if_resolved(self: Path, *args: object, **kwargs: object) -> Path:
        raise AssertionError("candidate resolve must not run before the link/junction check")

    monkeypatch.setattr(Path, "resolve", fail_if_resolved)

    with pytest.raises(OXRepositoryError):
        resolver.resolve_repository("example")


def test_repository_symlink_is_rejected_when_platform_supports_it(tmp_path: Path) -> None:
    projects, repository = _projects_with_repository(tmp_path)
    alias = projects / "linked"
    try:
        alias.symlink_to(repository, target_is_directory=True)
    except OSError:
        pytest.skip("platform does not permit directory symlink creation")

    resolver = OXScopeResolver(projects)

    with pytest.raises(OXRepositoryError):
        resolver.resolve_repository("linked")


def test_full_repository_scope_requires_no_paths(tmp_path: Path) -> None:
    projects, _ = _projects_with_repository(tmp_path)
    resolver = OXScopeResolver(projects)

    repository, scope = resolver.resolve_scope(
        "example",
        OXReviewMode.FULL_REPOSITORY,
        (),
        "Review the complete current repository",
    )

    assert repository.alias == "example"
    assert scope.repository == "example"
    assert scope.mode is OXReviewMode.FULL_REPOSITORY
    assert scope.paths == ()

    with pytest.raises(OXScopeError):
        resolver.resolve_scope(
            "example",
            OXReviewMode.FULL_REPOSITORY,
            ("src",),
            "Review everything",
        )


def test_bounded_scope_requires_existing_normalized_relative_paths(tmp_path: Path) -> None:
    projects, repository = _projects_with_repository(tmp_path)
    source = repository / "src"
    source.mkdir()
    (source / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    resolver = OXScopeResolver(projects)

    _, scope = resolver.resolve_scope(
        "example",
        OXReviewMode.BOUNDED,
        ("src", "src/example.py"),
        "Review the bounded implementation",
    )

    assert scope.paths == ("src", "src/example.py")

    with pytest.raises(OXScopeError):
        resolver.resolve_scope(
            "example",
            OXReviewMode.BOUNDED,
            (),
            "Review the bounded implementation",
        )
    with pytest.raises(OXScopeError):
        resolver.resolve_scope(
            "example",
            OXReviewMode.BOUNDED,
            ("missing.py",),
            "Review the bounded implementation",
        )


@pytest.mark.parametrize(
    "logical_path",
    (
        "",
        ".",
        "..",
        "/absolute",
        "../escape",
        "src/../escape",
        "src//example.py",
        "src/",
        r"src\example.py",
        "C:escape.py",
        "C:/escape.py",
        "bad\nname.py",
        "bad\x1fname.py",
    ),
)
def test_bounded_scope_rejects_unsafe_or_non_normalized_paths(
    tmp_path: Path,
    logical_path: str,
) -> None:
    projects, repository = _projects_with_repository(tmp_path)
    (repository / "src").mkdir()
    resolver = OXScopeResolver(projects)

    with pytest.raises(OXScopeError):
        resolver.resolve_scope(
            "example",
            OXReviewMode.BOUNDED,
            (logical_path,),
            "Review the bounded implementation",
        )


def test_bounded_scope_rejects_link_or_junction_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects, repository = _projects_with_repository(tmp_path)
    source = repository / "src"
    source.mkdir()
    (source / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    resolver = OXScopeResolver(projects)

    original = security.is_link_or_junction

    def mark_source_as_link(path: Path) -> bool:
        if path == source:
            return True
        return original(path)

    monkeypatch.setattr(security, "is_link_or_junction", mark_source_as_link)

    with pytest.raises(OXScopeError):
        resolver.resolve_scope(
            "example",
            OXReviewMode.BOUNDED,
            ("src/example.py",),
            "Review the bounded implementation",
        )


def test_bounded_scope_wraps_model_validation_as_scope_error(tmp_path: Path) -> None:
    projects, repository = _projects_with_repository(tmp_path)
    (repository / "src").mkdir()
    resolver = OXScopeResolver(projects)

    with pytest.raises(OXScopeError):
        resolver.resolve_scope(
            "example",
            OXReviewMode.BOUNDED,
            ("src",),
            "   ",
        )


def test_repository_example_config_contains_only_direct_child_targets() -> None:
    payload = json.loads(
        Path("config/ox-repositories.example.json").read_text(encoding="utf-8")
    )

    repositories = payload["repositories"]
    assert repositories
    for alias, directory in repositories.items():
        assert alias.strip() == alias
        assert directory.strip() == directory
        assert alias not in {".", ".."}
        assert directory not in {".", ".."}
        assert "/" not in alias and "\\" not in alias
        assert "/" not in directory and "\\" not in directory
        assert not Path(directory).is_absolute()
