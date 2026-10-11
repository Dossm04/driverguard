"""Pure availability checks; no database or external model calls required.

Run with: python -m pytest --confcutdir=unit_tests unit_tests/test_ai_availability.py
"""

from types import SimpleNamespace

import pytest

from app import ai_checklist


@pytest.mark.parametrize("provider", ["auto", "mock"])
def test_missing_provider_never_approves_unexamined_photos(monkeypatch, provider):
    settings = SimpleNamespace(ai_provider=provider, openai_compat_api_key="", gemini_api_key="")
    monkeypatch.setattr(ai_checklist, "get_settings", lambda: settings)

    def forbid_synthetic_approval():
        pytest.fail("A synthetic verdict must not enter the real photo-checking path")

    monkeypatch.setattr(ai_checklist, "mock_verdict", forbid_synthetic_approval)
    with pytest.raises(ai_checklist.AiError, match="ручная проверка"):
        ai_checklist.verify_photos(
            [ai_checklist.PhotoIn("tires", b"not an actual image", "image/png")]
        )


def test_unavailable_result_is_explicit_manual_review():
    verdict = ai_checklist.normalize(ai_checklist.unavailable_verdict())
    assert ai_checklist.compute_verdict(verdict) == "требует_внимания"
    for key in ai_checklist.AI_ITEM_KEYS:
        item = getattr(verdict, key)
        assert item.статус == "not_visible"
        assert item.confidence == 0
        assert "вручную" in item.комментарий
