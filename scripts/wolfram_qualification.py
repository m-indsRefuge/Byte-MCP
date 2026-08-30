"""Local score-only CLI for the Wolfram LLM API qualification campaign."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from byte_mcp.wolfram.qualification import (
    MEDIATED_DIALECT_VERSION,
    QUALIFICATION_MODES,
    QualificationScore,
    broad_coengineer_threshold_met,
    campaign_sha256,
    classify_capability_profile,
    incomplete_primary_task_ids,
    load_campaign,
    summarize,
    task_query_for_mode,
    task_route_reason_for_mode,
)

DEFAULT_CAMPAIGN = Path("qualification/wolfram/llm-api-v2.json")


def _default_scores() -> Path:
    profile = Path(os.path.expandvars("%USERPROFILE%"))
    if str(profile) == "%USERPROFILE%":
        profile = Path.home()
    return (
        profile
        / ".byte-mcp"
        / "wolfram"
        / "qualification"
        / "llm-api-v2-scores.jsonl"
    )


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _read_fixture_records(
    path: Path,
    fixture_hash: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("fixture_sha256") != fixture_hash:
            continue
        if mode is not None and record.get("mode") != mode:
            continue
        records.append(record)
    return records


def _read_scores(
    path: Path,
    fixture_hash: str,
    mode: str,
) -> list[QualificationScore]:
    scores: list[QualificationScore] = []
    for record in _read_fixture_records(path, fixture_hash, mode):
        if record.get("follow_up") is True:
            continue
        score_fields = {
            key: record.get(key) for key in QualificationScore.__dataclass_fields__
        }
        scores.append(QualificationScore(**score_fields))
    return scores


def command_list(args: argparse.Namespace) -> None:
    path = Path(args.campaign)
    tasks = load_campaign(path)
    print(
        json.dumps(
            {
                "campaign": str(path),
                "fixture_sha256": campaign_sha256(path),
                "task_count": len(tasks),
                "task_ids": [task.task_id for task in tasks],
                "modes": list(QUALIFICATION_MODES),
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_record(args: argparse.Namespace) -> None:
    campaign = Path(args.campaign)
    fixture_hash = campaign_sha256(campaign)
    tasks = {task.task_id: task for task in load_campaign(campaign)}
    task = tasks.get(args.task_id)
    if task is None:
        raise SystemExit(f"Unknown task ID: {args.task_id}")

    output = Path(args.scores)
    existing = _read_fixture_records(output, fixture_hash, args.mode)
    if args.follow_up:
        follow_up_count = sum(record.get("follow_up") is True for record in existing)
        if follow_up_count >= 5:
            raise SystemExit(
                f"Qualification follow-up limit of 5 reached for mode {args.mode}."
            )
    elif any(
        record.get("follow_up") is not True
        and record.get("task_id") == args.task_id
        for record in existing
    ):
        raise SystemExit(
            f"Primary score already recorded for task ID: {args.task_id} "
            f"in mode {args.mode}"
        )

    note = args.note.strip()
    if len(note) > 500:
        raise SystemExit("Byte-authored note must be at most 500 characters.")
    score = QualificationScore(
        task_id=args.task_id,
        correctness=args.correctness,
        specificity=args.specificity,
        evidence_quality=args.evidence_quality,
        engineering_usefulness=args.engineering_usefulness,
        unsupported_claim_discipline=args.unsupported_claim_discipline,
        hard_label=args.hard_label,
        defect_found=args.defect_found,
        root_cause_correct=args.root_cause_correct,
        location_correct=args.location_correct,
        fix_correct=args.fix_correct,
        tests_useful=args.tests_useful,
        invented_facts=args.invented_facts,
    )
    transmitted_query = task_query_for_mode(task, args.mode)
    route_reason = task_route_reason_for_mode(task, args.mode)
    record = {
        **asdict(score),
        "fixture_sha256": fixture_hash,
        "mode": args.mode,
        "transmitted_query_sha256": hashlib.sha256(
            transmitted_query.encode("utf-8")
        ).hexdigest(),
        "route_reason": route_reason,
        "dialect_version": (
            MEDIATED_DIALECT_VERSION if args.mode == "BYTE_MEDIATED" else None
        ),
        "follow_up": args.follow_up,
        "byte_baseline_correct": args.byte_baseline_correct,
        "note": note,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "recorded": args.task_id,
                "fixture_sha256": fixture_hash,
                "mode": args.mode,
                "follow_up": args.follow_up,
                "transmitted_query_sha256": record["transmitted_query_sha256"],
                "route_reason": route_reason,
            },
            sort_keys=True,
        )
    )


def command_summary(args: argparse.Namespace) -> None:
    campaign = Path(args.campaign)
    tasks = load_campaign(campaign)
    fixture_hash = campaign_sha256(campaign)
    scores_path = Path(args.scores)
    scores = _read_scores(scores_path, fixture_hash, args.mode)
    records = _read_fixture_records(scores_path, fixture_hash, args.mode)
    follow_up_count = sum(record.get("follow_up") is True for record in records)

    try:
        missing = incomplete_primary_task_ids(tasks, scores)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if missing:
        print(
            json.dumps(
                {
                    "classification": "INCOMPLETE",
                    "fixture_sha256": fixture_hash,
                    "mode": args.mode,
                    "primary_count": len(scores),
                    "follow_up_count": follow_up_count,
                    "missing_primary_task_ids": list(missing),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    summary = summarize(tasks, scores)
    improved = bool(args.byte_plus_wolfram_improved)
    payload = {
        "classification": "COMPLETE",
        "fixture_sha256": fixture_hash,
        "mode": args.mode,
        "overall_average": summary.overall_average,
        "family_averages": summary.family_averages,
        "classification_counts": summary.classification_counts,
        "coding_root_cause_correct_rate": summary.coding_root_cause_correct_rate,
        "unsupported_or_invented_rate": summary.unsupported_or_invented_rate,
        "computational_core_average": summary.computational_core_average,
        "primary_count": summary.primary_count,
        "follow_up_count": follow_up_count,
        "byte_plus_wolfram_improved": improved,
        "broad_coengineer_threshold_met": broad_coengineer_threshold_met(
            summary,
            byte_plus_wolfram_improved=improved,
        ),
        "capability_profile": classify_capability_profile(
            summary,
            byte_plus_wolfram_improved=improved,
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--campaign", default=str(DEFAULT_CAMPAIGN))
    parser.add_argument("--scores", default=str(_default_scores()))


def _add_mode(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", required=True, choices=QUALIFICATION_MODES)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score the fixed Wolfram LLM API campaign."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list")
    _add_common_paths(listing)
    listing.set_defaults(func=command_list)

    record = sub.add_parser("record")
    _add_common_paths(record)
    _add_mode(record)
    record.add_argument("task_id")
    for name in (
        "correctness",
        "specificity",
        "evidence-quality",
        "engineering-usefulness",
        "unsupported-claim-discipline",
    ):
        record.add_argument(
            f"--{name}",
            type=int,
            required=True,
            choices=range(5),
        )
    record.add_argument("--hard-label")
    for name in (
        "defect-found",
        "root-cause-correct",
        "location-correct",
        "fix-correct",
        "tests-useful",
        "invented-facts",
        "byte-baseline-correct",
    ):
        record.add_argument(f"--{name}", type=_optional_bool)
    record.add_argument("--follow-up", action="store_true")
    record.add_argument("--note", default="")
    record.set_defaults(func=command_record)

    summary = sub.add_parser("summary")
    _add_common_paths(summary)
    _add_mode(summary)
    summary.add_argument("--byte-plus-wolfram-improved", action="store_true")
    summary.set_defaults(func=command_summary)
    return parser


def main() -> None:
    args = _parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
