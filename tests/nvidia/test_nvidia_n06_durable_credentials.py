from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"

LAUNCHER_NVIDIA = SCRIPTS / "Launcher.Nvidia.ps1"
SETUP_NVIDIA = SCRIPTS / "Setup-NvidiaCredential.ps1"
TEST_NVIDIA = SCRIPTS / "Test-NvidiaCredential.ps1"
REMOVE_NVIDIA = SCRIPTS / "Remove-NvidiaCredential.ps1"
START_BYTE_MCP = SCRIPTS / "Start-ByteMCP.ps1"

EXPECTED_CREDENTIAL_SUFFIX = ".byte-mcp/secrets/nvidia-api-key.dpapi"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\\", "/")


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return read_text(path)


def tracked_nvidia_python_sources() -> list[Path]:
    src = REPO / "src" / "byte_mcp"
    return sorted(
        path
        for path in src.rglob("*.py")
        if "nvidia" in path.as_posix().lower()
    )


def test_n06_required_scripts_exist() -> None:
    assert LAUNCHER_NVIDIA.is_file()
    assert SETUP_NVIDIA.is_file()
    assert TEST_NVIDIA.is_file()
    assert REMOVE_NVIDIA.is_file()


def test_n06_launcher_declares_required_functions() -> None:
    text = read_text_if_exists(LAUNCHER_NVIDIA)
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
    text = read_text_if_exists(LAUNCHER_NVIDIA)
    assert ".byte-mcp" in text
    assert "secrets" in text
    assert "nvidia-api-key.dpapi" in text
    assert EXPECTED_CREDENTIAL_SUFFIX.endswith(
        ".byte-mcp/secrets/nvidia-api-key.dpapi"
    )


def test_n06_setup_uses_secure_prompt_and_explicit_replace() -> None:
    text = read_text_if_exists(SETUP_NVIDIA)
    assert "Read-Host" in text
    assert "-AsSecureString" in text
    assert re.search(r"(?im)\[switch\]\s*\$Replace\b", text)
    assert not re.search(
        r"(?im)param\s*\([^)]*(ApiKey|NvidiaApiKey|CredentialText)",
        text,
    )


def test_n06_scripts_never_persist_user_or_machine_api_key() -> None:
    joined = "\n".join(
        read_text_if_exists(path)
        for path in (
            LAUNCHER_NVIDIA,
            SETUP_NVIDIA,
            TEST_NVIDIA,
            REMOVE_NVIDIA,
        )
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
        read_text_if_exists(path)
        for path in (
            LAUNCHER_NVIDIA,
            SETUP_NVIDIA,
            TEST_NVIDIA,
            REMOVE_NVIDIA,
        )
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
    if ($value -ne 'synthetic-n06-secret') {{
        throw 'round trip mismatch'
    }}
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
        assert "synthetic-n06-secret" not in result.stdout
        assert "synthetic-n06-secret" not in result.stderr


def test_n06_missing_store_reports_absent() -> None:
    if os.name != "nt":
        return

    with tempfile.TemporaryDirectory() as td:
        path = (Path(td) / "missing.dpapi").as_posix()
        script = rf"""
. '{LAUNCHER_NVIDIA.as_posix()}'
$state = Test-NvidiaCredentialStore -Path '{path}'
$state | ConvertTo-Json -Compress
"""
        result = run_pwsh(script)
        assert result.returncode == 0, result.stderr
        state = json.loads(result.stdout.strip().splitlines()[-1])
        assert state["State"] == "ABSENT"
        assert state["Exists"] is False
        assert state["AclSafe"] is False
        assert state["ProtectionScope"] == "CurrentUser"


def test_n06_corrupt_store_reports_invalid_without_secret_output() -> None:
    if os.name != "nt":
        return

    with tempfile.TemporaryDirectory() as td:
        path_obj = Path(td) / "credential.dpapi"
        path_obj.write_bytes(b"not-a-valid-dpapi-payload")
        path = path_obj.as_posix()
        script = rf"""
. '{LAUNCHER_NVIDIA.as_posix()}'
$state = Test-NvidiaCredentialStore -Path '{path}'
$state | ConvertTo-Json -Compress
"""
        result = run_pwsh(script)
        assert result.returncode == 0, result.stderr
        state = json.loads(result.stdout.strip().splitlines()[-1])
        assert state["State"] == "INVALID"
        assert state["Exists"] is True
        assert state["ProtectionScope"] == "CurrentUser"
        assert "not-a-valid-dpapi-payload" not in result.stdout
        assert "not-a-valid-dpapi-payload" not in result.stderr


def test_n06_dpapi_rotation_replaces_verified_blob_without_temp_leak() -> None:
    if os.name != "nt":
        return

    with tempfile.TemporaryDirectory() as td:
        directory = Path(td)
        path = (directory / "credential.dpapi").as_posix()
        script = rf"""
. '{LAUNCHER_NVIDIA.as_posix()}'
$old = ConvertTo-SecureString 'synthetic-n06-old' -AsPlainText -Force
$new = ConvertTo-SecureString 'synthetic-n06-new' -AsPlainText -Force
Protect-NvidiaCredential -Credential $old -Path '{path}'
Protect-NvidiaCredential -Credential $new -Path '{path}'
$value = Unprotect-NvidiaCredential -Path '{path}'
try {{
    if ($value -ne 'synthetic-n06-new') {{
        throw 'rotation mismatch'
    }}
    Write-Output 'ROTATION=PASS'
}}
finally {{
    $value = $null
}}
"""
        result = run_pwsh(script)
        assert result.returncode == 0, result.stderr
        assert "ROTATION=PASS" in result.stdout
        assert "synthetic-n06-old" not in result.stdout
        assert "synthetic-n06-new" not in result.stdout
        assert list(directory.glob("*.tmp")) == []
        assert list(directory.glob("*.tmp.*")) == []

def test_n06_operator_scripts_dot_source_launcher_module() -> None:
    for path in (SETUP_NVIDIA, TEST_NVIDIA, REMOVE_NVIDIA):
        text = read_text_if_exists(path)
        assert "Launcher.Nvidia.ps1" in text


def test_n06_setup_does_not_restart_byte_mcp() -> None:
    text = read_text_if_exists(SETUP_NVIDIA).lower()
    assert "start-bytemcp.ps1" not in text
    assert "stop-bytemcp.ps1" not in text


def test_n06_remove_does_not_restart_byte_mcp() -> None:
    text = read_text_if_exists(REMOVE_NVIDIA).lower()
    assert "start-bytemcp.ps1" not in text
    assert "stop-bytemcp.ps1" not in text


def test_n06_operator_scripts_do_not_accept_plaintext_key_parameter() -> None:
    joined = "\n".join(
        read_text_if_exists(path)
        for path in (SETUP_NVIDIA, TEST_NVIDIA, REMOVE_NVIDIA)
    )
    assert not re.search(
        r"(?im)\b(ApiKey|NvidiaApiKey|CredentialText|PlainTextKey)\b"
        r"\s*(?:=|,|\))",
        joined,
    )


def test_n06_setup_receipt_requires_restart_without_provider_call() -> None:
    text = read_text_if_exists(SETUP_NVIDIA)
    assert "DAEMON_RESTART_REQUIRED=YES" in text
    assert "PROVIDER_CALLS=0" in text
    assert "DPAPI_SCOPE=CURRENT_USER" in text


def test_n06_test_command_is_provider_free_and_requires_available_store() -> None:
    text = read_text_if_exists(TEST_NVIDIA)
    assert "Test-NvidiaCredentialStore" in text
    assert 'State -ne "AVAILABLE"' in text
    assert "PROVIDER_CALLS=0" in text
    assert "NVIDIA_CREDENTIAL_TEST=PASS" in text


def test_n06_remove_is_idempotent_by_guarding_file_removal() -> None:
    text = read_text_if_exists(REMOVE_NVIDIA)
    assert "Test-Path" in text
    assert "Remove-Item" in text
    assert "CREDENTIAL_FILE_PRESENT=NO" in text
    assert "PROVIDER_CALLS=0" in text
