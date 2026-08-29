"""Local score-only CLI for the Wolfram LLM API qualification campaign."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from byte_mcp.wolfram.qualification import (
    QualificationScore,
    broad_coengineer_threshold_met,
    campaign_sha256,
    load_campaign,
    summarize,
)

DEFAULT_CAMPAIGN = Path("qualification/wolfram/llm-api-v1.json")


def _default_scores() -> Path:
    profile = Path(os.path.expandvars("%USERPROFILE%"))
    if str(profile) == "%USERPROFILE%":
        profile = Path.home()
    return profile / ".byte-mcp" / "wolfram" / "qualification" / "llm-api-v1-scores.jsonl"


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _read_scores(path: Path, fixture_hash: str) -> list[QualificationScore]:
    scores: list[QualificationScore] = []
    if not path.exists():
        return scores
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("fixture_sha256") != fixture_hash or record.get("follow_up") is True:
            continue
        score_fields = {key: record.get(key) for key in QualificationScore.__dataclass_fields__}
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
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_record(args: argparse.Namespace) -> None:
    campaign = Path(args.campaign)
    fixture_hash = campaign_sha256(campaign)
    task_ids = {task.task_id for task in load_campaign(campaign)}
    if args.task_id not in task_ids:
        raise SystemExit(f"Unknown task ID: {args.task_id}")
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
    record = {
        **asdict(score),
        "fixture_sha256": fixture_hash,
        "follow_up": args.follow_up,
        "byte_baseline_correct": args.byte_baseline_correct,
        "note": note,
    }
    output = Path(args.scores)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps({"recorded": args.task_id, "fixture_sha256": fixture_hash}, sort_keys=True))


def command_summary(args: argparse.Namespace) -> None:
    campaign = Path(args.campaign)
    fixture_hash = campaign_sha256(campaign)
    scores = _read_scores(Path(args.scores), fixture_hash)
    summary = summarize(scores)
    improved = bool(args.byte_plus_wolfram_improved)
    payload = {
        "fixture_sha256": fixture_hash,
        "overall_average": summary.overall_average,
        "family_averages": summary.family_averages,
        "classification_counts": summary.classification_counts,
        "coding_root_cause_correct_rate": summary.coding_root_cause_correct_rate,
        "unsupported_or_invented_rate": summary.unsupported_or_invented_rate,
        "primary_count": summary.primary_count,
        "byte_plus_wolfram_improved": improved,
        "broad_coengineer_threshold_met": broad_coengineer_threshold_met(
            summary,
            byte_plus_wolfram_improved=improved,
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--campaign", default=str(DEFAULT_CAMPAIGN))
    parser.add_argument("--scores", default=str(_default_scores()))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score the fixed Wolfram LLM API campaign.")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list")
    _add_common_paths(listing)
    listing.set_defaults(func=command_list)

    record = sub.add_parser("record")
    _add_common_paths(record)
    record.add_argument("task_id")
    for name in (
        "correctness",
        "specificity",
        "evidence-quality",
        "engineering-usefulness",
        "unsupported-claim-discipline",
    ):
        record.add_argument(f"--{name}", type=int, required=True, choices=range(5))
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
    summary.add_argument("--byte-plus-wolfram-improved", action="store_true")
    summary.set_defaults(func=command_summary)
    return parser


def main() -> None:
    args = _parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
