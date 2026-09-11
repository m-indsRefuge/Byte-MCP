from __future__ import annotations

import json
from datetime import UTC, datetime

from byte_mcp.nvidia.canary import (
    NVIDIA_LIGHTNING_CANARY_MODEL_ID,
    NVIDIA_LIGHTNING_CANARY_PROMPT,
    prepare_lightning_canary,
)
from byte_mcp.nvidia.canary_evidence import NvidiaCanaryEvidenceStore


def test_lightning_canary_explicitly_disables_thinking_in_immutable_body(tmp_path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")

    receipt = prepare_lightning_canary(
        store,
        now=lambda: datetime(2026, 9, 10, 12, 30, tzinfo=UTC),
    )
    snapshot = store.load(receipt.canary_id)
    body = json.loads(snapshot.request_body)

    assert body == {
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 64,
        "messages": [{"content": NVIDIA_LIGHTNING_CANARY_PROMPT, "role": "user"}],
        "model": NVIDIA_LIGHTNING_CANARY_MODEL_ID,
        "n": 1,
        "stream": False,
        "temperature": 1.0,
        "top_p": 0.95,
    }
    assert "reasoning_budget" not in body
