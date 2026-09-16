# NVIDIA-06 Durable Credential Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable Windows DPAPI-backed NVIDIA credential store that automatically injects `NVIDIA_API_KEY` into the Byte-MCP daemon at startup without storing the plaintext key in Git, files, ChatGPT, or User/Machine environment variables.

**Architecture:** A PowerShell launcher module owns DPAPI CurrentUser protection, safe file handling, ACL validation, process-scope injection, and cleanup. Three explicit operator scripts provide setup/rotation, provider-free validation, and removal. `Start-ByteMCP.ps1` consumes the module immediately around the existing daemon child-process creation so the child inherits the key and the launcher clears its own copy. NVIDIA Python provider code remains unchanged.

**Tech Stack:** PowerShell 7, Windows DPAPI (`System.Security.Cryptography.ProtectedData`), Windows ACLs, Python 3.12, pytest, Ruff, Git, existing Byte-MCP launcher/runtime/qualification infrastructure.

**Spec:** `docs/superpowers/specs/2026-09-16-nvidia-n06-durable-credential-bootstrap-design.md`

## Global Constraints

- Production predecessor is `a1a9bdbad6ba3990226ae01f622f11a5a799879a`; the approved NVIDIA-06 design commit is `f364e7788a3929601137cae7c1e8fbfdf3fb4dca`.
- Implementation must occur in an isolated worktree/branch created from the committed NVIDIA-06 planning HEAD, not by editing the live runtime.
- Recommended branch: `feat/nvidia-provider-n06-durable-credential-bootstrap`.
- Recommended worktree: `C:\Users\nolan\AIProjects\Byte-MCP-nvidia-n06-durable-credential-bootstrap`.
- Protected production credential path is `%USERPROFILE%\.byte-mcp\secrets\nvidia-api-key.dpapi`.
- DPAPI scope is `CurrentUser`.
- The protected file is an opaque DPAPI ciphertext blob; no JSON secret envelope in V1.
- Setup accepts the credential only from `Read-Host -AsSecureString`; there is no API-key command-line parameter.
- Rotation requires explicit `-Replace`.
- Setup, rotation, test, removal, unit tests, qualification, and promotion make zero NVIDIA provider requests.
- `NVIDIA_API_KEY` must remain absent from Windows User and Machine environment scopes.
- Credential absence/invalidity must not prevent Byte-MCP from starting; NVIDIA remains locally unavailable instead.
- Existing public MCP surface remains exactly 8 production tools and exactly 3 NVIDIA tools.
- Existing NVIDIA Python settings/transmit/model-registry contracts remain unchanged.
- No OX calls. No Wolfram calls. No NVIDIA provider calls until a separately authorized post-promotion canary.
- No automatic retry, fallback, provider discovery, or model substitution.
- Significant credential failure boundaries must be recorded in `FAILURE_MAP.md`.
- No implementation milestone is complete until relevant failure-map entries and regression tests are present.
- Do not store the credential, a credential substring, its length, its hash, ciphertext bytes, or an authorization header in receipts/logs.
- Preserve the current live runtime until provider-free implementation qualification is complete.

---

## File Structure

### Create

- `scripts/Launcher.Nvidia.ps1` — reusable DPAPI, protected-file, ACL, injection, cleanup, and safe-store-status functions.
- `scripts/Setup-NvidiaCredential.ps1` — secure first enrollment and explicit `-Replace` rotation.
- `scripts/Test-NvidiaCredential.ps1` — provider-free durable-store health check.
- `scripts/Remove-NvidiaCredential.ps1` — idempotent protected-store removal.
- `tests/nvidia/test_nvidia_n06_durable_credentials.py` — static and executable contract tests for credential scripts and launcher integration.
- `tests/nvidia/test_nvidia_n06_qualification.py` — committed qualification artifact freshness and invariant tests.
- `scripts/nvidia_n06_durable_credential_qualification.py` — provider-free qualification generator.
- `qualification/nvidia-n06/offline-qualification.json` — deterministic committed provider-free qualification artifact.

### Modify

- `scripts/Start-ByteMCP.ps1` — narrow pre-child credential import and post-child cleanup around existing daemon start.
- `FAILURE_MAP.md` — NVIDIA-06 failure boundaries.
- `.gitignore` only if the repository has an existing user-secret pattern that should defensively include `.byte-mcp`/secret artifacts; do not add a repository-local secret path or imply the protected production blob belongs in the repository.

### Must remain functionally unchanged

- NVIDIA MCP public tool signatures.
- NVIDIA Python settings/provider transport behavior.
- Frozen model alias/registry contents.
- `nvidia_review` formal approval semantics.
- OX and Wolfram implementation.

---

### Task 1: Establish RED NVIDIA-06 security and file-contract tests

**Files:**
- Create: `tests/nvidia/test_nvidia_n06_durable_credentials.py`
- Read only: `scripts/Start-ByteMCP.ps1`
- Read only: `src/byte_mcp/` NVIDIA settings/provider modules

**Interfaces:**
- Consumes: approved NVIDIA-06 spec.
- Produces: failing tests that define required script names, protected path, forbidden persistence patterns, provider-free credential-management boundary, and unchanged NVIDIA Python public boundary.

- [ ] **Step 1: Create static contract helpers**

Add helpers that resolve the repository root and read PowerShell files as UTF-8 text:

```python
from __future__ import annotations

from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"

LAUNCHER_NVIDIA = SCRIPTS / "Launcher.Nvidia.ps1"
SETUP_NVIDIA = SCRIPTS / "Setup-NvidiaCredential.ps1"
TEST_NVIDIA = SCRIPTS / "Test-NvidiaCredential.ps1"
REMOVE_NVIDIA = SCRIPTS / "Remove-NvidiaCredential.ps1"
START_BYTE_MCP = SCRIPTS / "Start-ByteMCP.ps1"

EXPECTED_CREDENTIAL_SUFFIX = (
    ".byte-mcp/secrets/nvidia-api-key.dpapi"
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\\", "/")


def tracked_nvidia_python_sources() -> list[Path]:
    src = REPO / "src" / "byte_mcp"
    return sorted(
        p for p in src.rglob("*.py")
        if "nvidia" in p.as_posix().lower()
    )
```

- [ ] **Step 2: Add RED file/exposure tests**

Add:

```python
def test_n06_required_scripts_exist() -> None:
    assert LAUNCHER_NVIDIA.is_file()
    assert SETUP_NVIDIA.is_file()
    assert TEST_NVIDIA.is_file()
    assert REMOVE_NVIDIA.is_file()


def test_n06_launcher_declares_required_functions() -> None:
    text = read_text(LAUNCHER_NVIDIA)
    for name in (
        "Get-NvidiaCredentialPath",
        "Protect-NvidiaCredential",
        "Unprotect-NvidiaCredential",
        "Test-NvidiaCredentialStore",
        "Import-NvidiaCredentialForChildProcess",
        "Clear-NvidiaCredentialFromCurrentProcess",
    ):
        assert re.search(
            rf"(?im)^\s*function\s+{re.escape(name)}\b",
            text,
        ), name


def test_n06_protected_path_contract_is_present() -> None:
    text = read_text(LAUNCHER_NVIDIA)
    assert ".byte-mcp" in text
    assert "secrets" in text
    assert "nvidia-api-key.dpapi" in text


def test_n06_setup_uses_secure_prompt_and_explicit_replace() -> None:
    text = read_text(SETUP_NVIDIA)
    assert "Read-Host" in text
    assert "-AsSecureString" in text
    assert re.search(r"(?im)\[switch\]\s*\$Replace\b", text)
    assert not re.search(
        r"(?im)param\s*\([^)]*(ApiKey|NvidiaApiKey|CredentialText)",
        text,
    )
```

- [ ] **Step 3: Add RED forbidden-persistence/provider tests**

Add:

```python
def test_n06_scripts_never_persist_user_or_machine_api_key() -> None:
    joined = "\n".join(
        read_text(path)
        for path in (
            LAUNCHER_NVIDIA,
            SETUP_NVIDIA,
            TEST_NVIDIA,
            REMOVE_NVIDIA,
        )
        if path.exists()
    )

    forbidden = (
        'SetEnvironmentVariable("NVIDIA_API_KEY", "User")',
        'SetEnvironmentVariable("NVIDIA_API_KEY", "Machine")',
        "setx NVIDIA_API_KEY",
        "[EnvironmentVariableTarget]::User",
        "[EnvironmentVariableTarget]::Machine",
    )
    for needle in forbidden:
        assert needle.lower() not in joined.lower()


def test_n06_credential_scripts_have_no_provider_or_network_execution() -> None:
    joined = "\n".join(
        read_text(path)
        for path in (
            LAUNCHER_NVIDIA,
            SETUP_NVIDIA,
            TEST_NVIDIA,
            REMOVE_NVIDIA,
        )
        if path.exists()
    ).lower()

    for forbidden in (
        "invoke-restmethod",
        "invoke-webrequest",
        "curl ",
        "nvidia_query",
        "nvidia_review",
        "wolfram_query",
        "ox_review",
        "/v1/chat/completions",
        "integrate.api.nvidia.com",
    ):
        assert forbidden not in joined
```

- [ ] **Step 4: Add RED startup-integration and Python-boundary tests**

Add tests that require `Start-ByteMCP.ps1` to dot-source `Launcher.Nvidia.ps1`, call import before the daemon launch, and call cleanup in a `finally` block:

```python
def test_n06_start_launcher_integrates_nvidia_module() -> None:
    text = read_text(START_BYTE_MCP)
    assert "Launcher.Nvidia.ps1" in text
    assert "Import-NvidiaCredentialForChildProcess" in text
    assert "Clear-NvidiaCredentialFromCurrentProcess" in text
    assert "finally" in text.lower()


def test_n06_python_layer_does_not_read_dpapi_blob() -> None:
    joined = "\n".join(
        read_text(path)
        for path in tracked_nvidia_python_sources()
    ).lower()

    assert "nvidia-api-key.dpapi" not in joined
    assert "protecteddata" not in joined
    assert "dataprotectionscope" not in joined
```

- [ ] **Step 5: Run the RED test file**

Run:

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest tests/nvidia/test_nvidia_n06_durable_credentials.py -q
```

Expected: FAIL because the four NVIDIA-06 scripts and startup integration do not exist yet. Existing NVIDIA Python-boundary assertions should pass.

- [ ] **Step 6: Commit RED tests**

```powershell
git add -- tests/nvidia/test_nvidia_n06_durable_credentials.py
git commit -m "test: define NVIDIA durable credential contract"
```

---

### Task 2: Implement the DPAPI launcher credential module

**Files:**
- Create: `scripts/Launcher.Nvidia.ps1`
- Modify: `tests/nvidia/test_nvidia_n06_durable_credentials.py`

**Interfaces:**
- Consumes: Windows current-user profile and optional internal `-Path` arguments for test isolation.
- Produces:
  - `Get-NvidiaCredentialPath -> string`
  - `Protect-NvidiaCredential -Credential SecureString [-Path string] -> void`
  - `Unprotect-NvidiaCredential [-Path string] -> string`
  - `Test-NvidiaCredentialStore [-Path string] -> PSCustomObject`
  - `Import-NvidiaCredentialForChildProcess [-Path string] -> bool`
  - `Clear-NvidiaCredentialFromCurrentProcess -> void`

- [ ] **Step 1: Add executable PowerShell test helper**

Extend the Python test file:

```python
import json
import os
import subprocess
import tempfile

POWERSHELL = "pwsh"


def run_pwsh(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
```

Skip executable DPAPI tests when `os.name != "nt"`.

- [ ] **Step 2: Add RED round-trip/absence/corruption tests**

Add Windows-only tests that create a temp path and dot-source the launcher module.

Round-trip test command shape:

```python
def test_n06_dpapi_round_trip_at_temp_path() -> None:
    if os.name != "nt":
        return

    with tempfile.TemporaryDirectory() as td:
        path = (Path(td) / "credential.dpapi").as_posix()
        script = rf"""
. '{LAUNCHER_NVIDIA.as_posix()}'
$secure = ConvertTo-SecureString 'synthetic-n06-secret' -AsPlainText -Force
Protect-NvidiaCredential -Credential $secure -Path '{path}'
$value = Unprotect-NvidiaCredential -Path '{path}'
try {{
    if ($value -ne 'synthetic-n06-secret') {{ throw 'round trip mismatch' }}
    $state = Test-NvidiaCredentialStore -Path '{path}'
    $state | ConvertTo-Json -Compress
}}
finally {{
    $value = $null
}}
"""
        result = run_pwsh(script)
        assert result.returncode == 0, result.stderr
        state = json.loads(result.stdout.strip().splitlines()[-1])
        assert state["State"] == "AVAILABLE"
        assert state["Exists"] is True
        assert state["AclSafe"] is True
        assert state["ProtectionScope"] == "CurrentUser"
```

Add:

```python
def test_n06_missing_store_reports_absent() -> None:
    ...
    assert state["State"] == "ABSENT"
    assert state["Exists"] is False


def test_n06_corrupt_store_reports_invalid_without_secret_output() -> None:
    ...
    assert state["State"] == "INVALID"
    assert "synthetic-n06-secret" not in result.stdout
    assert "synthetic-n06-secret" not in result.stderr
```

- [ ] **Step 3: Run targeted RED DPAPI tests**

Run:

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest `
  tests/nvidia/test_nvidia_n06_durable_credentials.py `
  -k "dpapi or missing_store or corrupt_store" -q
```

Expected: FAIL because the module has not been implemented.

- [ ] **Step 4: Implement module constants and path resolution**

Create `scripts/Launcher.Nvidia.ps1` with:

```powershell
Set-StrictMode -Version Latest

$script:NvidiaCredentialFileName = "nvidia-api-key.dpapi"
$script:NvidiaCredentialProtectionScope = "CurrentUser"

function Get-NvidiaCredentialPath {
    [CmdletBinding()]
    param()

    $HomePath = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::UserProfile
    )
    if ([string]::IsNullOrWhiteSpace($HomePath)) {
        throw "NVIDIA_CREDENTIAL_USER_PROFILE_UNAVAILABLE"
    }

    return [System.IO.Path]::Combine(
        $HomePath,
        ".byte-mcp",
        "secrets",
        $script:NvidiaCredentialFileName
    )
}
```

- [ ] **Step 5: Implement private byte/ACL helpers**

Implement private helpers:

```powershell
function Clear-NvidiaByteArray {
    param([byte[]] $Bytes)
    if ($null -ne $Bytes) {
        [Array]::Clear($Bytes, 0, $Bytes.Length)
    }
}

function Assert-NvidiaCredentialAclSafe {
    param([Parameter(Mandatory)] [string] $Path)

    $Acl = Get-Acl -LiteralPath $Path
    foreach ($Rule in $Acl.Access) {
        $Identity = $Rule.IdentityReference.Value
        $Rights = $Rule.FileSystemRights
        $AllowsWrite = (
            $Rights.ToString() -match
            "Write|Modify|FullControl|CreateFiles|AppendData"
        )
        if (
            $Rule.AccessControlType -eq "Allow" -and
            $AllowsWrite -and
            $Identity -match
            "(^|\\)(Everyone|Users|Authenticated Users)$"
        ) {
            throw "NVIDIA_CREDENTIAL_ACL_UNSAFE"
        }
    }
}
```

Do not wholesale replace profile ACL inheritance.

- [ ] **Step 6: Implement DPAPI protection with atomic replacement**

`Protect-NvidiaCredential` must:

1. accept `SecureString`;
2. convert to BSTR only inside `try/finally`;
3. encode UTF-8 bytes;
4. call `[System.Security.Cryptography.ProtectedData]::Protect(..., CurrentUser)`;
5. create the secrets directory;
6. write ciphertext to a unique temp file in the same directory;
7. ACL-check temp file;
8. decrypt temp file and verify the resulting plaintext is non-empty;
9. atomically replace/move temp file into final path;
10. validate final file;
11. zero plaintext/ciphertext byte arrays and BSTR memory in `finally`.

Use:

```powershell
$Scope = [System.Security.Cryptography.DataProtectionScope]::CurrentUser
$CipherBytes = [System.Security.Cryptography.ProtectedData]::Protect(
    $PlainBytes,
    $null,
    $Scope
)
```

When a prior credential exists, use a same-volume atomic replacement primitive; otherwise use same-directory `Move-Item`.

- [ ] **Step 7: Implement DPAPI unprotect and safe state**

`Unprotect-NvidiaCredential` reads the opaque bytes and calls:

```powershell
$PlainBytes = [System.Security.Cryptography.ProtectedData]::Unprotect(
    $CipherBytes,
    $null,
    [System.Security.Cryptography.DataProtectionScope]::CurrentUser
)
```

Return the decoded string only to the caller; never write it to output except as the function return value.

`Test-NvidiaCredentialStore` returns only:

```powershell
[pscustomobject]@{
    State = "AVAILABLE" # or ABSENT / INVALID
    Exists = $true
    AclSafe = $true
    ProtectionScope = "CurrentUser"
}
```

Catch decryption/ACL failures and convert them to `INVALID` without embedding the raw exception message in safe receipts.

- [ ] **Step 8: Implement process injection and cleanup**

```powershell
function Import-NvidiaCredentialForChildProcess {
    [CmdletBinding()]
    param(
        [string] $Path = (Get-NvidiaCredentialPath)
    )

    $State = Test-NvidiaCredentialStore -Path $Path
    if ($State.State -ne "AVAILABLE") {
        return $false
    }

    $Plain = $null
    try {
        $Plain = Unprotect-NvidiaCredential -Path $Path
        if ([string]::IsNullOrWhiteSpace($Plain)) {
            return $false
        }

        $env:NVIDIA_API_KEY = $Plain
        return $true
    }
    finally {
        $Plain = $null
    }
}

function Clear-NvidiaCredentialFromCurrentProcess {
    [CmdletBinding()]
    param()

    Remove-Item Env:NVIDIA_API_KEY -ErrorAction SilentlyContinue
}
```

- [ ] **Step 9: Run DPAPI and static tests**

Run:

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest tests/nvidia/test_nvidia_n06_durable_credentials.py -q
```

Expected: remaining failures are only for the three operator scripts and `Start-ByteMCP.ps1` integration; module-specific tests pass.

- [ ] **Step 10: Commit module**

```powershell
git add -- `
  scripts/Launcher.Nvidia.ps1 `
  tests/nvidia/test_nvidia_n06_durable_credentials.py
git commit -m "feat: add DPAPI NVIDIA credential module"
```

---

### Task 3: Implement setup, rotation, test, and removal commands

**Files:**
- Create: `scripts/Setup-NvidiaCredential.ps1`
- Create: `scripts/Test-NvidiaCredential.ps1`
- Create: `scripts/Remove-NvidiaCredential.ps1`
- Modify: `tests/nvidia/test_nvidia_n06_durable_credentials.py`

**Interfaces:**
- Consumes: `Launcher.Nvidia.ps1`.
- Produces: explicit operator commands with no provider access.

- [ ] **Step 1: Add RED static command-contract tests**

Add assertions:

```python
def test_n06_operator_scripts_dot_source_launcher_module() -> None:
    for path in (SETUP_NVIDIA, TEST_NVIDIA, REMOVE_NVIDIA):
        assert "Launcher.Nvidia.ps1" in read_text(path)


def test_n06_setup_does_not_restart_byte_mcp() -> None:
    text = read_text(SETUP_NVIDIA).lower()
    assert "start-bytemcp.ps1" not in text
    assert "stop-bytemcp.ps1" not in text


def test_n06_remove_does_not_restart_byte_mcp() -> None:
    text = read_text(REMOVE_NVIDIA).lower()
    assert "start-bytemcp.ps1" not in text
    assert "stop-bytemcp.ps1" not in text
```

- [ ] **Step 2: Implement setup/rotation script**

`Setup-NvidiaCredential.ps1` must:

- declare only `[switch] $Replace`;
- dot-source `Launcher.Nvidia.ps1`;
- verify User/Machine `NVIDIA_API_KEY` are absent;
- refuse an existing store unless `-Replace`;
- prompt with `Read-Host "NVIDIA API key" -AsSecureString`;
- call `Protect-NvidiaCredential`;
- call `Test-NvidiaCredentialStore`;
- require `AVAILABLE`;
- emit only:

```text
NVIDIA_CREDENTIAL_SETUP=PASS
DPAPI_PROTECTED_CREDENTIAL=PASS
DPAPI_SCOPE=CURRENT_USER
PLAINTEXT_SECRET_FILE=NONE
NVIDIA_API_KEY_USER=ABSENT
NVIDIA_API_KEY_MACHINE=ABSENT
PROVIDER_CALLS=0
DAEMON_RESTART_REQUIRED=YES
```

For replacement add `CREDENTIAL_ROTATED=PASS`; for first enrollment add `CREDENTIAL_ENROLLED=PASS`.

- [ ] **Step 3: Implement provider-free test script**

`Test-NvidiaCredential.ps1`:

- dot-sources the module;
- requires User/Machine env absent;
- calls `Test-NvidiaCredentialStore`;
- returns nonzero unless `AVAILABLE`;
- prints only safe state fields;
- prints `PROVIDER_CALLS=0`.

- [ ] **Step 4: Implement idempotent removal**

`Remove-NvidiaCredential.ps1`:

- dot-sources the module;
- gets the final path;
- if present, removes only that file;
- verifies it is absent;
- does not remove the `.byte-mcp` root or unrelated secret files;
- verifies User/Machine env remain absent;
- prints:

```text
NVIDIA_CREDENTIAL_REMOVAL=PASS
CREDENTIAL_FILE_PRESENT=NO
NVIDIA_API_KEY_USER=ABSENT
NVIDIA_API_KEY_MACHINE=ABSENT
PROVIDER_CALLS=0
DAEMON_RESTART_REQUIRED=YES
```

Repeated invocation must remain successful.

- [ ] **Step 5: Add executable temp-path module tests for rotation/removal semantics**

Test atomic replacement directly through module functions using a temp path:

1. protect `synthetic-n06-old`;
2. protect `synthetic-n06-new` to the same path;
3. unprotect and require exactly `synthetic-n06-new`;
4. assert no `.tmp` siblings remain.

Do not automate the interactive setup prompt in pytest; test its secure-prompt contract statically and test cryptographic replacement through the module.

- [ ] **Step 6: Run credential tests**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest tests/nvidia/test_nvidia_n06_durable_credentials.py -q
```

Expected: only startup integration tests remain RED.

- [ ] **Step 7: Commit operator commands**

```powershell
git add -- `
  scripts/Setup-NvidiaCredential.ps1 `
  scripts/Test-NvidiaCredential.ps1 `
  scripts/Remove-NvidiaCredential.ps1 `
  tests/nvidia/test_nvidia_n06_durable_credentials.py
git commit -m "feat: add NVIDIA credential lifecycle commands"
```

---

### Task 4: Integrate durable credentials into `Start-ByteMCP.ps1`

**Files:**
- Modify: `scripts/Start-ByteMCP.ps1`
- Modify: `tests/nvidia/test_nvidia_n06_durable_credentials.py`

**Interfaces:**
- Consumes: `Import-NvidiaCredentialForChildProcess` and `Clear-NvidiaCredentialFromCurrentProcess`.
- Produces: a daemon process that inherits `NVIDIA_API_KEY` only when the protected store is valid, while the launcher clears its own process copy.

- [ ] **Step 1: Add RED ordering test**

Add a test that locates the relevant call positions:

```python
def test_n06_startup_import_precedes_cleanup() -> None:
    text = read_text(START_BYTE_MCP)
    import_at = text.index("Import-NvidiaCredentialForChildProcess")
    clear_at = text.index("Clear-NvidiaCredentialFromCurrentProcess")
    assert import_at < clear_at
```

Also require a `try`/`finally` boundary around child launch in the startup script.

- [ ] **Step 2: Dot-source the NVIDIA launcher module**

Near the existing launcher-module imports, add:

```powershell
. (Join-Path $PSScriptRoot "Launcher.Nvidia.ps1")
```

Do not import NVIDIA Python provider code into the PowerShell launcher.

- [ ] **Step 3: Wrap only the existing daemon child-process creation**

Immediately before the existing daemon launch statement:

```powershell
$NvidiaCredentialInjected = $false

try {
    $NvidiaCredentialInjected =
        Import-NvidiaCredentialForChildProcess

    if ($NvidiaCredentialInjected) {
        Write-Host "NVIDIA_CREDENTIAL_STATE=AVAILABLE"
    }
    else {
        $State = Test-NvidiaCredentialStore
        Write-Host "NVIDIA_CREDENTIAL_STATE=$($State.State)"
    }

    # Execute the repository's existing Byte-MCP child-process launch
    # statement here without changing its command, arguments, port,
    # working directory, log redirection, or readiness behavior.
}
finally {
    Clear-NvidiaCredentialFromCurrentProcess
}
```

During implementation, the existing launch statement must be moved intact into this `try` block rather than rewritten.

The `finally` block must execute whether child creation succeeds or fails.

- [ ] **Step 4: Preserve graceful degradation**

If `Import-NvidiaCredentialForChildProcess` returns `$false`, startup must continue through the pre-existing server start path. Do not throw solely because NVIDIA is absent/invalid.

Unsafe/corrupt credential state may produce a safe warning such as:

```text
NVIDIA_CREDENTIAL_STATE=INVALID
```

but no raw exception containing secret-derived data.

- [ ] **Step 5: Add parent-process cleanup test**

Add an executable Windows test that:

1. creates a protected temp credential;
2. dot-sources the module;
3. imports it;
4. asserts `$env:NVIDIA_API_KEY` exists;
5. calls cleanup;
6. asserts `$env:NVIDIA_API_KEY` is absent.

- [ ] **Step 6: Run focused NVIDIA-06 tests**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest tests/nvidia/test_nvidia_n06_durable_credentials.py -q
```

Expected: PASS.

- [ ] **Step 7: Run existing NVIDIA runtime tests**

Run the full NVIDIA suite:

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest tests/nvidia -q
```

Expected: PASS; zero provider requests.

- [ ] **Step 8: Commit startup integration**

```powershell
git add -- `
  scripts/Start-ByteMCP.ps1 `
  tests/nvidia/test_nvidia_n06_durable_credentials.py
git commit -m "feat: inject durable NVIDIA credential at startup"
```

---

### Task 5: Add failure-aware engineering documentation

**Files:**
- Modify: `FAILURE_MAP.md`
- Modify: `tests/nvidia/test_nvidia_n06_durable_credentials.py`

**Interfaces:**
- Consumes: implemented credential lifecycle.
- Produces: durable diagnosis/recovery guidance for each significant failure boundary.

- [ ] **Step 1: Determine the next failure-map ID**

Read the final existing `F<number>` identifier in `FAILURE_MAP.md`. Assign consecutive new IDs to all NVIDIA-06 entries; do not renumber prior entries.

- [ ] **Step 2: Add the seven required boundaries**

Add one section each for:

1. protected credential missing;
2. protected credential corrupt / DPAPI decrypt failure;
3. unsafe credential-file ACL;
4. atomic replacement failure;
5. launcher injection failure;
6. stale daemon credential after rotation/removal;
7. wrong Windows identity/profile.

Each section must contain:

- boundary/symptom;
- likely cause;
- first diagnostic;
- propagation;
- safe recovery;
- data/credential risk;
- explicit “do not” warning;
- related tests.

The recovery rules must preserve these invariants:

```text
No plaintext fallback.
No User/Machine env workaround.
No provider request during credential diagnosis.
No assumption that deleting/rotating the file revokes a running daemon.
```

- [ ] **Step 3: Add failure-map presence test**

Add a test that reads `FAILURE_MAP.md` and requires the seven normalized phrases from the approved spec.

- [ ] **Step 4: Run focused tests and diff check**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest tests/nvidia/test_nvidia_n06_durable_credentials.py -q

git diff --check
```

Expected: PASS.

- [ ] **Step 5: Commit failure documentation**

```powershell
git add -- FAILURE_MAP.md tests/nvidia/test_nvidia_n06_durable_credentials.py
git commit -m "docs: map NVIDIA credential failure boundaries"
```

---

### Task 6: Build deterministic provider-free NVIDIA-06 qualification

**Files:**
- Create: `scripts/nvidia_n06_durable_credential_qualification.py`
- Create: `qualification/nvidia-n06/offline-qualification.json`
- Create: `tests/nvidia/test_nvidia_n06_qualification.py`

**Interfaces:**
- Consumes: committed NVIDIA-06 source and docs.
- Produces: deterministic metadata-only qualification artifact with zero provider calls.

- [ ] **Step 1: Write RED qualification freshness test**

Create:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ARTIFACT = (
    REPO
    / "qualification"
    / "nvidia-n06"
    / "offline-qualification.json"
)
SCRIPT = REPO / "scripts" / "nvidia_n06_durable_credential_qualification.py"


def test_n06_committed_qualification_matches_fresh_report(
    tmp_path: Path,
) -> None:
    fresh = tmp_path / "offline-qualification.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(fresh),
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    assert json.loads(ARTIFACT.read_text(encoding="utf-8")) == json.loads(
        fresh.read_text(encoding="utf-8")
    )
```

- [ ] **Step 2: Run RED freshness test**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest `
  tests/nvidia/test_nvidia_n06_qualification.py `
  -q
```

Expected: FAIL because the generator/artifact are absent.

- [ ] **Step 3: Implement deterministic qualification generator**

The generator must compute and emit:

```json
{
  "schema_version": "nvidia-n06-durable-credential-qualification-v1",
  "status": "PASS",
  "provider_calls": 0,
  "checks": {
    "dpapi_current_user_contract": "PASS",
    "protected_path_contract": "PASS",
    "secure_prompt_contract": "PASS",
    "replace_is_explicit": "PASS",
    "user_env_persistence_absent": "PASS",
    "machine_env_persistence_absent": "PASS",
    "credential_scripts_provider_free": "PASS",
    "startup_graceful_degradation_contract": "PASS",
    "launcher_cleanup_contract": "PASS",
    "python_dpapi_boundary_absent": "PASS",
    "failure_map_n06": "PASS",
    "exact_8_tool_surface": "PASS",
    "exact_3_nvidia_surface": "PASS"
  }
}
```

Also include SHA-256 fields for the credential scripts, `Start-ByteMCP.ps1`, and `FAILURE_MAP.md` using raw file bytes. Sort JSON keys and terminate with one newline.

The qualification generator must not read the production protected credential blob and must not read `NVIDIA_API_KEY`.

- [ ] **Step 4: Generate artifact**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  scripts/nvidia_n06_durable_credential_qualification.py `
  --output qualification/nvidia-n06/offline-qualification.json
```

Expected terminal summary:

```text
NVIDIA_N06_OFFLINE_QUALIFICATION=PASS
NVIDIA_PROVIDER_CALLS=0
```

- [ ] **Step 5: Run freshness and all NVIDIA-06 tests**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest `
  tests/nvidia/test_nvidia_n06_durable_credentials.py `
  tests/nvidia/test_nvidia_n06_qualification.py `
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit qualification**

```powershell
git add -- `
  scripts/nvidia_n06_durable_credential_qualification.py `
  qualification/nvidia-n06/offline-qualification.json `
  tests/nvidia/test_nvidia_n06_qualification.py
git commit -m "test: qualify NVIDIA durable credential bootstrap"
```

---

### Task 7: Run complete provider-free implementation gates

**Files:**
- No intended source changes.
- If a gate finds a defect, repair only the responsible NVIDIA-06 files and rerun the failed gate plus affected regressions before committing the repair.

**Interfaces:**
- Consumes: complete NVIDIA-06 implementation.
- Produces: evidence that implementation is safe to promote without contacting any provider.

- [ ] **Step 1: Verify branch/worktree identity**

Run:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
```

Require the NVIDIA-06 feature branch and a clean worktree before qualification begins.

- [ ] **Step 2: Run NVIDIA-06 focused tests**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest `
  tests/nvidia/test_nvidia_n06_durable_credentials.py `
  tests/nvidia/test_nvidia_n06_qualification.py `
  -q
```

Expected: PASS.

- [ ] **Step 3: Run complete NVIDIA regression**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m pytest tests/nvidia -q
```

Expected: PASS.

- [ ] **Step 4: Run runtime integration tests**

Run the repository's established Byte-MCP runtime/integration pytest targets used by NVIDIA-05 qualification. Preserve the previously documented exclusion of the five stale OX baseline-mismatch files only if those exact unchanged failures still exist; do not broaden the exclusion set.

Expected: all supported regression tests PASS.

- [ ] **Step 5: Run Ruff**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m ruff check src tests scripts
```

Expected: PASS.

- [ ] **Step 6: Run Python compile/import checks**

```powershell
& "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe" `
  -m compileall -q src tests scripts
```

Expected: PASS.

- [ ] **Step 7: Run diff/static guards**

```powershell
git diff --check
git status --short
```

Run a tracked-source secret scan that rejects credential-shaped `nvapi-` literals outside deliberately synthetic test patterns.

Expected: no secret-bearing tracked content and no unintended changes.

- [ ] **Step 8: Regenerate qualification and prove freshness**

Generate to a temporary path, compare parsed JSON to the committed artifact, and require equality.

Expected:

```text
NVIDIA_N06_OFFLINE_QUALIFICATION=PASS
NVIDIA_PROVIDER_CALLS=0
```

- [ ] **Step 9: Record provider-free implementation receipt**

Record only safe evidence:

```text
NVIDIA_N06_IMPLEMENTATION_QUALIFICATION=PASS
NVIDIA_PROVIDER_CALLS=0
OX_PROVIDER_CALLS=0
WOLFRAM_PROVIDER_CALLS=0
NVIDIA_REGRESSION=PASS
SUPPORTED_BROAD_REGRESSION=PASS
RUFF=PASS
COMPILEALL=PASS
DIFF_CHECK=PASS
RUNTIME_MUTATIONS=0
```

Do not make a live NVIDIA request.

---

### Task 8: Provider-free promotion and durable restart proof

**Files:**
- Production runtime checkout only through the existing controlled Byte-MCP promotion procedure.
- Protected credential created by the operator using `Setup-NvidiaCredential.ps1`.
- No source edits in the runtime.

**Interfaces:**
- Consumes: exact qualified NVIDIA-06 commit.
- Produces: production runtime that starts using the DPAPI-protected credential with no manual API-key bootstrap.

- [ ] **Step 1: Capture exact promotion identities**

Record:

```text
PREDECESSOR_COMMIT=<current production runtime HEAD>
TARGET_COMMIT=<qualified NVIDIA-06 HEAD>
```

Require source feature worktree clean and target commit reachable from the source repository.

- [ ] **Step 2: Promote exact target commit provider-free**

Use the established controlled Byte-MCP runtime promotion path:

1. require current runtime clean;
2. stop MCP daemon;
3. checkout detached exact NVIDIA-06 target commit;
4. run committed NVIDIA-06 qualification;
5. run NVIDIA tests/runtime checks;
6. verify exact 8-tool production surface;
7. start MCP daemon;
8. require ports 8000 and 8080 READY;
9. require clean runtime.

No provider calls.

- [ ] **Step 3: Enroll durable credential once**

From the promoted trusted scripts, run:

```powershell
.\scripts\Setup-NvidiaCredential.ps1
```

Enter the existing NVIDIA API key only at the secure prompt.

Require:

```text
NVIDIA_CREDENTIAL_SETUP=PASS
DPAPI_PROTECTED_CREDENTIAL=PASS
DPAPI_SCOPE=CURRENT_USER
NVIDIA_API_KEY_USER=ABSENT
NVIDIA_API_KEY_MACHINE=ABSENT
PROVIDER_CALLS=0
DAEMON_RESTART_REQUIRED=YES
```

- [ ] **Step 4: Provider-free store test**

Run:

```powershell
.\scripts\Test-NvidiaCredential.ps1
```

Require:

```text
NVIDIA_CREDENTIAL_TEST=PASS
CREDENTIAL_STATE=AVAILABLE
PROVIDER_CALLS=0
```

- [ ] **Step 5: Restart Byte-MCP without manually entering the key**

Use normal production stop/start scripts only. Do not run the old temporary credential bootstrap.

Require startup evidence:

```text
NVIDIA_CREDENTIAL_STATE=AVAILABLE
```

and:

```text
MCP_8000_READY=PASS
TUNNEL_8080_READY=PASS
TOTAL_MCP_TOOLS=8
NVIDIA_MCP_TOOLS=3
RUNTIME_WORKTREE_CLEAN=PASS
```

- [ ] **Step 6: Prove parent/persistent environment state**

After restart, in the operator process verify:

```powershell
[Environment]::GetEnvironmentVariable("NVIDIA_API_KEY", "User")
[Environment]::GetEnvironmentVariable("NVIDIA_API_KEY", "Machine")
```

Both must be empty.

The launcher process must also have cleared its process-scope copy after child creation.

- [ ] **Step 7: Record provider-free promotion receipt**

Record:

```text
NVIDIA_N06_PROVIDER_FREE_PROMOTION=PASS
DURABLE_STORE=AVAILABLE
RESTART_WITHOUT_MANUAL_KEY_ENTRY=PASS
NVIDIA_API_KEY_USER=ABSENT
NVIDIA_API_KEY_MACHINE=ABSENT
TOTAL_MCP_TOOLS=8
NVIDIA_MCP_TOOLS=3
NVIDIA_PROVIDER_CALLS=0
RUNTIME_WORKTREE_CLEAN=PASS
MCP_8000_READY=PASS
TUNNEL_8080_READY=PASS
NEXT=FRESH_EXPLICIT_AUTHORIZATION_FOR_ONE_LIGHTNING_DURABLE_CREDENTIAL_CANARY
```

Hard stop. No canary without fresh authorization.

---

### Task 9: One separately authorized durable-credential live canary

**Files:**
- No source changes.

**Interfaces:**
- Consumes: promoted NVIDIA-06 runtime with durable credential loaded automatically at startup.
- Produces: one terminal live qualification result.

- [ ] **Step 1: Obtain fresh explicit authorization**

The operator must explicitly authorize exactly one `nvidia_query` provider request for this durable credential qualification.

Do not reuse any prior NVIDIA-05/F2 authorization.

- [ ] **Step 2: Preflight current public tool surface**

In a fresh ChatGPT thread/schema view, confirm:

```text
TOTAL_BYTE_MCP_TOOLS=8
NVIDIA_TOOLS=3
NVIDIA_QUERY_EXPOSED=YES
```

If `nvidia_query` is absent, stop with zero provider requests.

- [ ] **Step 3: Invoke one Lightning canary**

Use:

```text
model alias: lightning
system prompt: none
prompt: Return exactly the string NVIDIA-N06-DURABLE-CREDENTIAL-OK and nothing else.
```

Exactly one call. No retry, fallback, substitution, direct provider call, formal review, OX, or Wolfram.

- [ ] **Step 4: Record terminal evidence**

Capture safe fields only:

```text
NVIDIA_N06_DURABLE_CANARY=<PASS or terminal typed failure>
MODEL_ALIAS=lightning
RESOLVED_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
PROVIDER_REQUESTS=1
RETRIES=0
FALLBACK=NONE
SUBSTITUTION=NONE
```

On success require exact response:

```text
NVIDIA-N06-DURABLE-CREDENTIAL-OK
```

Regardless of outcome, hard stop after the single request.

- [ ] **Step 5: Mark NVIDIA-06 complete only after successful canary**

Successful completion means:

```text
DPAPI_PROTECTED_CREDENTIAL=PASS
NVIDIA_API_KEY_USER=ABSENT
NVIDIA_API_KEY_MACHINE=ABSENT
RESTART_WITHOUT_MANUAL_KEY_ENTRY=PASS
PROVIDER_FREE_PROMOTION=PASS
DURABLE_CREDENTIAL_LIVE_CANARY=PASS
NVIDIA_PROVIDER_REQUESTS_FOR_CANARY=1
RETRIES=0
```

---

## Plan Self-Review

### Spec coverage

- DPAPI CurrentUser storage: Tasks 2, 3, 6.
- Opaque protected blob: Task 2.
- Exact production path: Tasks 1, 2.
- Secure prompt only: Tasks 1, 3.
- Explicit rotation: Task 3.
- Explicit removal: Task 3.
- Provider-free test command: Task 3.
- Automatic startup injection: Task 4.
- Graceful degradation: Task 4.
- Parent cleanup: Tasks 2, 4.
- No User/Machine persistence: Tasks 1–4, 6, 8.
- ACL policy: Task 2.
- Atomic replacement: Task 2.
- Failure map: Task 5.
- Deterministic qualification artifact: Task 6.
- NVIDIA/broad/static regressions: Task 7.
- Controlled provider-free promotion: Task 8.
- Restart without manual bootstrap: Task 8.
- Fresh one-request canary: Task 9.
- No OX/Wolfram/provider calls before canary: Global Constraints and Tasks 1–8.

### Type/interface consistency

The PowerShell function names and behavior in Tasks 1–4 match the approved design. Test-only isolation is achieved with optional `-Path` parameters on storage functions; the production path remains the default and the public operator scripts expose no credential-path or plaintext-key parameter.

### Placeholder scan

The plan contains no implementation placeholders. Where `Start-ByteMCP.ps1` must retain its existing daemon-launch statement, the plan explicitly requires moving that existing statement intact rather than inventing a replacement command without repository evidence.
