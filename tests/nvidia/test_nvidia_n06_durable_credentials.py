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
