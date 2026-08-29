from pathlib import Path

from dulwich import porcelain

AUTHOR = b"OX Test <ox-test@example.invalid>"


def write_file(repository_path: Path, path: str, content: bytes) -> None:
    target = repository_path / Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def commit_files(repository_path: Path, files: dict[str, bytes], message: bytes) -> str:
    for path, content in files.items():
        write_file(repository_path, path, content)
    porcelain.add(repository_path, paths=list(files))
    return porcelain.commit(repository_path, message=message, author=AUTHOR).decode("ascii")


def create_repository(tmp_path: Path) -> tuple[Path, str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repository_path = tmp_path / "fixture-repository"
    porcelain.init(repository_path)
    base = commit_files(
        repository_path,
        {
            "src/alpha.py": b"value = 'base'\n",
            "src/nested/beta.py": b"beta = True\n",
            "tests/test_alpha.py": b"def test_alpha(): pass\n",
            "README.md": b"base readme\n",
        },
        b"base",
    )
    target = commit_files(
        repository_path,
        {
            "src/alpha.py": b"value = 'target'\n",
            "src/gamma.py": b"gamma = True\n",
        },
        b"target",
    )
    return repository_path, base, target
