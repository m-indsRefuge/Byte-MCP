param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$src = Join-Path $repo "src"

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    $resolvedPython = Get-Command $PythonPath -ErrorAction Stop
    $PythonPath = $resolvedPython.Source
}

$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $src

    $probe = @"
import hashlib
from pathlib import Path

from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.settings import OXSettings

REPO = Path(r"$repo")

EXPECTED = {
    "OX-000007": {
        "attempt": "8CF1C74D821D4D4A284A51C2506B1841EB23EE3176EEEFE5398FC572329B5263",
        "prepared": "0F527FB5708A995BFF1C97D918A91C9439754975482266B16D9D5D3FBE49B467",
        "events": "2C35D56D9848B6C5696CD6E43E77D719DA11AC8CAA45A6F2044237D0BF57D6D0",
        "manifest": "6962745AF66B692A97DAC42BC885D4A29689A63FC43035F69D67003A566BB1BB",
        "review": "5C907CD263AD6D35E97278582082A9B0E8CFFB6E7A3AE2409E95D349CDEFA3A9",
        "thread": "FA75C1824685BC27670CAA30D3065F35D597F812F1671D71111CC0042299EDAC",
        "outcome": "OUTCOME_UNKNOWN",
    },
    "OX-000008": {
        "attempt": "7F920BE548D6E3FF85BB52C8EDBD29DE1E405483D2CFDC1EACAEC0AF37BF7BDB",
        "prepared": "40283E202E22BCCB326861E328FEC52BDB382642335B14D320D02F3EF1A81749",
        "events": "54451FC2F9413E8AB65B2485DDF5E980DBC8D731C0B2C1957B2960259FCE7539",
        "manifest": "D739DD9F1F13BA5210A2ECA9110A61AB95086EB302FDB15E41936FE2821702E4",
        "review": "79905994B3E06C309ABDB72B0B0893B3AB9F1A32F0F1DC98C414D3DE11325C5D",
        "thread": "EE0274686E11041CFC14E86E69528FCD06F93F77F21D4F7068289B7C97DE45CA",
        "outcome": "OUTCOME_UNKNOWN",
    },
    "OX-000009": {
        "attempt": "B20CFFA0BDC45D71B4A1B1CEE7AAF9B4D4668C95E2F8B717505716810F938367",
        "prepared": "5000E26055528F8C7017909247445A00FCB0C6656B69AEA6329C530D0E67E2C0",
        "events": "3EAC98A517840F69E9220D8C132738092B48CD7F37C872411C16A1B7CC790949",
        "manifest": "41848DE962AD2974B14EB560BAD2E04EA58F11DADFF636965036B832CC633781",
        "response": "BE3CE837351F082C5CB4228EC18642107BEF2D24E2A3359861F3FE8C7F97FCCF",
        "review": "DD9154754DAEA06CCB3BCD6F2184812F86FEF24D97010548BD5A848B1790D750",
        "thread": "CF4FFFDA1DA7EB7F708A130FD7DE87EFBFC1F6C46ADA4EFE890111715D4AEA26",
        "outcome": "COMPLETED",
    },
}

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()

settings = OXSettings.load(REPO)
root = settings.evidence_root
print(f"evidence_root={root}")

if not root.is_dir():
    raise SystemExit("configured OX evidence root does not exist")

store = EvidenceStore(root)

for review_id, expected in EXPECTED.items():
    review_dir = root / "reviews" / review_id
    if not review_dir.is_dir():
        raise SystemExit(f"{review_id}: review directory is missing")

    review = store.get_review(review_id)
    attempts = review.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 1:
        raise SystemExit(f"{review_id}: expected exactly one attempt")

    attempt = attempts[0]
    expected_attempt_id = f"{review_id}-A001"
    if attempt.get("attempt_id") != expected_attempt_id:
        raise SystemExit(f"{review_id}: expected only {expected_attempt_id}")
    if attempt.get("outcome") != expected["outcome"]:
        raise SystemExit(
            f"{review_id}: expected outcome {expected['outcome']}, "
            f"got {attempt.get('outcome')}"
        )

    a002 = review_dir / "attempts" / f"{review_id}-A002.json"
    if a002.exists():
        raise SystemExit(f"{review_id}: A002 exists unexpectedly")

    paths = {
        "attempt": review_dir / "attempts" / f"{review_id}-A001.json",
        "prepared": review_dir / "bundles" / "prepared.json",
        "events": review_dir / "events.jsonl",
        "manifest": review_dir / "manifest.json",
        "review": review_dir / "review.json",
        "thread": review_dir / "threads" / "initial.jsonl",
    }
    if review_id == "OX-000009":
        paths["response"] = (
            review_dir / "responses" / f"{review_id}-A001.json"
        )

    for label, path in paths.items():
        if not path.is_file():
            raise SystemExit(f"{review_id}: missing {label} evidence")
        actual = digest(path)
        expected_hash = expected[label]
        if actual != expected_hash:
            raise SystemExit(
                f"{review_id}: {label} fingerprint changed\n"
                f"expected={expected_hash}\n"
                f"actual={actual}"
            )

    print(
        f"{review_id}: PASS "
        f"attempt={expected_attempt_id} "
        f"outcome={expected['outcome']} "
        "A002=absent"
    )

print("OX_Q03G_HISTORICAL_EVIDENCE_ACCEPTANCE: PASS")
"@

    & $PythonPath -c $probe
    if ($LASTEXITCODE -ne 0) {
        throw "OX Q03G historical evidence acceptance failed."
    }
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}