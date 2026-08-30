from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from byte_mcp.wolfram.qualification import campaign_sha256

REPO_ROOT = Path(__file__).parents[2]
SCRIPT = REPO_ROOT / "scripts" / "wolfram_qualification.py"
CAMPAIGN_V2 = REPO_ROOT / "qualification" / "wolfram" / "llm-api-v2.json"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _record_args(scores: Path, task_id: str, *extra: str) -> tuple[str, ...]:
    return (
        "record",
        "--campaign",
        str(CAMPAIGN_V2),
        "--scores",
        str(scores),
        task_id,
        "--correctness",
        "4",
        "--specificity",
        "4",
        "--evidence-quality",
        "4",
        "--engineering-usefulness",
        "4",
        "--unsupported-claim-discipline",
        "4",
        *extra,
    )


def test_default_campaign_is_v2() -> None:
    result = _run("list")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload["campaign"]).parts[-3:] == (
        "qualification",
        "wolfram",
        "llm-api-v2.json",
    )
    assert payload["task_count"] == 30


def test_record_rejects_duplicate_primary_score(tmp_path: Path) -> None:
    scores = tmp_path / "scores.jsonl"
    first = _run(*_record_args(scores, "WA-01-01"))
    assert first.returncode == 0, first.stderr

    duplicate = _run(*_record_args(scores, "WA-01-01"))
    assert duplicate.returncode != 0
    assert "Primary score already recorded" in duplicate.stderr


def test_record_enforces_five_follow_up_limit(tmp_path: Path) -> None:
    scores = tmp_path / "scores.jsonl"
    for _ in range(5):
        result = _run(*_record_args(scores, "WA-01-01", "--follow-up"))
        assert result.returncode == 0, result.stderr

    sixth = _run(*_record_args(scores, "WA-01-01", "--follow-up"))
    assert sixth.returncode != 0
    assert "follow-up limit of 5" in sixth.stderr


def test_summary_reports_incomplete_without_profile(tmp_path: Path) -> None:
    scores = tmp_path / "scores.jsonl"
    recorded = _run(*_record_args(scores, "WA-01-01"))
    assert recorded.returncode == 0, recorded.stderr

    result = _run(
        "summary",
        "--campaign",
        str(CAMPAIGN_V2),
        "--scores",
        str(scores),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["classification"] == "INCOMPLETE"


def test_summary_requires_complete_primary_campaign_for_profile(tmp_path: Path) -> None:
    scores = tmp_path / "scores.jsonl"
    for task_number in range(1, 31):
        task_id = f"WA-{((task_number - 1) // 3) + 1:02d}-{((task_number - 1) % 3) + 1:02d}"
        recorded = _run(*_record_args(scores, task_id))
        assert recorded.returncode == 0, recorded.stderr

    result = _run(
        "summary",
        "--campaign",
        str(CAMPAIGN_V2),
        "--scores",
        str(scores),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["classification"] in {
        "COMPUTATION_SPECIALIST",
        "BOUNDED_CODE_ASSISTANT",
        "COENGINEER_CANDIDATE",
        "FALLBACK_VALIDATOR",
        "DO_NOT_INTEGRATE",
    }


def test_list_hash_matches_qualification_module() -> None:
    result = _run("list", "--campaign", str(CAMPAIGN_V2))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["campaign_sha256"] == campaign_sha256(CAMPAIGN_V2)
