from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePath

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


def _record_args(
    scores: Path,
    task_id: str,
    *extra: str,
    mode: str = "RAW",
) -> tuple[str, ...]:
    return (
        "record",
        "--campaign",
        str(CAMPAIGN_V2),
        "--scores",
        str(scores),
        "--mode",
        mode,
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
    campaign = PurePath(payload["campaign"].replace("\\", "/"))
    assert campaign.parts[-3:] == (
        "qualification",
        "wolfram",
        "llm-api-v2.json",
    )
    assert payload["task_count"] == 30
    assert payload["modes"] == ["BYTE_MEDIATED", "RAW"]


def test_record_persists_mode_and_exact_transmitted_query_hash(tmp_path: Path) -> None:
    scores = tmp_path / "scores.jsonl"
    raw = _run(*_record_args(scores, "WA-01-01", mode="RAW"))
    mediated = _run(*_record_args(scores, "WA-01-01", mode="BYTE_MEDIATED"))
    assert raw.returncode == 0, raw.stderr
    assert mediated.returncode == 0, mediated.stderr

    records = [
        json.loads(line)
        for line in scores.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [record["mode"] for record in records] == ["RAW", "BYTE_MEDIATED"]
    assert records[0]["transmitted_query_sha256"] == hashlib.sha256(
        b"Compute 2^100 exactly."
    ).hexdigest()
    assert records[0]["route_reason"] == "DIRECT_COMPUTATION"
    assert records[0]["dialect_version"] is None
    assert records[1]["transmitted_query_sha256"] == hashlib.sha256(
        b"2^100"
    ).hexdigest()
    assert records[1]["route_reason"] == "DIRECT_COMPUTATION"
    assert records[1]["dialect_version"] == "wolfram-native-v0.1"


def test_record_rejects_duplicate_primary_only_within_same_mode(tmp_path: Path) -> None:
    scores = tmp_path / "scores.jsonl"
    first = _run(*_record_args(scores, "WA-01-01", mode="RAW"))
    assert first.returncode == 0, first.stderr

    duplicate = _run(*_record_args(scores, "WA-01-01", mode="RAW"))
    assert duplicate.returncode != 0
    assert "Primary score already recorded" in duplicate.stderr

    mediated = _run(*_record_args(scores, "WA-01-01", mode="BYTE_MEDIATED"))
    assert mediated.returncode == 0, mediated.stderr


def test_record_enforces_five_follow_up_limit_per_mode(tmp_path: Path) -> None:
    scores = tmp_path / "scores.jsonl"
    for _ in range(5):
        result = _run(
            *_record_args(scores, "WA-01-01", "--follow-up", mode="RAW")
        )
        assert result.returncode == 0, result.stderr

    sixth = _run(*_record_args(scores, "WA-01-01", "--follow-up", mode="RAW"))
    assert sixth.returncode != 0
    assert "follow-up limit of 5" in sixth.stderr

    mediated = _run(
        *_record_args(scores, "WA-01-01", "--follow-up", mode="BYTE_MEDIATED")
    )
    assert mediated.returncode == 0, mediated.stderr


def test_summary_reports_incomplete_without_profile(tmp_path: Path) -> None:
    scores = tmp_path / "scores.jsonl"
    recorded = _run(*_record_args(scores, "WA-01-01", mode="RAW"))
    assert recorded.returncode == 0, recorded.stderr

    result = _run(
        "summary",
        "--campaign",
        str(CAMPAIGN_V2),
        "--scores",
        str(scores),
        "--mode",
        "RAW",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["classification"] == "INCOMPLETE"
    assert payload["mode"] == "RAW"
    assert payload["primary_count"] == 1
    assert len(payload["missing_primary_task_ids"]) == 29
    assert "capability_profile" not in payload
    assert "broad_coengineer_threshold_met" not in payload


def test_complete_summary_emits_capability_profile(tmp_path: Path) -> None:
    fixture_hash = campaign_sha256(CAMPAIGN_V2)
    scores = tmp_path / "scores.jsonl"
    records: list[str] = []
    for family in range(1, 11):
        for item in range(1, 4):
            task_id = f"WA-{family:02d}-{item:02d}"
            record = {
                "task_id": task_id,
                "correctness": 3,
                "specificity": 3,
                "evidence_quality": 3,
                "engineering_usefulness": 3,
                "unsupported_claim_discipline": 3,
                "hard_label": None,
                "defect_found": None,
                "root_cause_correct": (
                    True if task_id in {
                        "WA-04-02",
                        "WA-04-03",
                        "WA-05-01",
                        "WA-05-02",
                        "WA-05-03",
                    } else None
                ),
                "location_correct": None,
                "fix_correct": None,
                "tests_useful": None,
                "invented_facts": False,
                "fixture_sha256": fixture_hash,
                "follow_up": False,
                "byte_baseline_correct": None,
                "note": "",
                "mode": "BYTE_MEDIATED",
                "transmitted_query_sha256": "0" * 64,
                "route_reason": "DIRECT_COMPUTATION",
                "dialect_version": "wolfram-native-v0.1",
            }
            records.append(json.dumps(record, sort_keys=True))
    scores.write_text("\n".join(records) + "\n", encoding="utf-8")

    result = _run(
        "summary",
        "--campaign",
        str(CAMPAIGN_V2),
        "--scores",
        str(scores),
        "--mode",
        "BYTE_MEDIATED",
        "--byte-plus-wolfram-improved",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["classification"] == "COMPLETE"
    assert payload["mode"] == "BYTE_MEDIATED"
    assert payload["primary_count"] == 30
    assert payload["capability_profile"] == "A_BROAD_COENGINEER"
    assert payload["broad_coengineer_threshold_met"] is True
