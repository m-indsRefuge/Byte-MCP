import json
from types import SimpleNamespace

import pytest

V1_POLICY = {
    "schema_version": 1,
    "enabled": True,
    "root_alias": "projects",
    "protected_projects": ["Byte-MCP"],
    "allow_new_projects": True,
    "allow_cross_project_moves": False,
    "allow_binary_writes": False,
    "snapshot_existing": True,
    "delete_mode": "recoverable",
    "allow_permanent_delete": False,
    "require_prepare_commit": True,
    "allow_self_commit": True,
    "max_operations": 200,
    "max_file_bytes": 1_000_000,
    "max_staged_bytes": 20_000_000,
    "max_directory_entries": 20_000,
    "max_directory_bytes": 250_000_000,
    "max_patch_bytes": 1_000_000,
    "transaction_ttl_seconds": 900,
    "recovery_retention_days": 30,
    "recovery_max_bytes": 2_147_483_648,
}


@pytest.fixture
def write_env(tmp_path):
    projects = tmp_path / "AIProjects"
    private = tmp_path / "private-write"
    state_dir = private / "state"
    projects.mkdir()
    state_dir.mkdir(parents=True)
    policy_file = private / "policy.json"
    policy_file.write_text(json.dumps(V1_POLICY), encoding="utf-8")
    assert private.resolve() != projects.resolve()
    assert projects.resolve() not in private.resolve().parents
    return SimpleNamespace(
        projects=projects,
        private=private,
        state_dir=state_dir,
        policy_file=policy_file,
    )


@pytest.fixture
def write_policy_file(write_env):
    return write_env.policy_file
