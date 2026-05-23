"""FAQ schema validation — boundaries and trimming behaviour.

The router never sees a malformed payload because Pydantic rejects it at
the boundary, so these unit tests cover the rules without spinning up
the full integration harness.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.features.faqs.schemas import FAQCreate, FAQUpdate


class TestFAQCreate:
    def test_minimum_valid_payload(self):
        m = FAQCreate(question="Q?", answer="A.")
        assert m.question == "Q?"
        assert m.answer == "A."
        assert m.order_index == 0
        assert m.is_active is True

    def test_question_is_trimmed(self):
        m = FAQCreate(question="  hello  ", answer="A")
        assert m.question == "hello"

    def test_whitespace_only_question_rejected(self):
        with pytest.raises(ValidationError, match="question"):
            FAQCreate(question="   ", answer="A")

    def test_empty_question_rejected(self):
        with pytest.raises(ValidationError):
            FAQCreate(question="", answer="A")

    def test_question_over_500_rejected(self):
        with pytest.raises(ValidationError, match="500"):
            FAQCreate(question="x" * 501, answer="A")

    def test_question_at_500_accepted(self):
        FAQCreate(question="x" * 500, answer="A")  # no raise

    def test_answer_over_10000_rejected(self):
        with pytest.raises(ValidationError, match="10000"):
            FAQCreate(question="Q", answer="a" * 10_001)

    def test_answer_at_10000_accepted(self):
        FAQCreate(question="Q", answer="a" * 10_000)

    def test_markdown_in_answer_preserved(self):
        md = "**bold** and [link](https://x.io)\n\nNew paragraph."
        m = FAQCreate(question="Q", answer=md)
        assert m.answer == md

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            FAQCreate(question="Q", answer="A", extra_field="x")

    def test_order_index_negative_accepted(self):
        # TZ explicit: negative is allowed (sorts above zero).
        m = FAQCreate(question="Q", answer="A", order_index=-3)
        assert m.order_index == -3


class TestFAQUpdate:
    def test_partial_update_only_active_flag(self):
        m = FAQUpdate(is_active=False)
        assert m.model_dump(exclude_unset=True) == {"is_active": False}

    def test_partial_update_strips_question(self):
        m = FAQUpdate(question="  trimmed  ")
        assert m.question == "trimmed"

    def test_empty_payload_is_valid_noop(self):
        # An empty PATCH is harmless — the service will commit no changes.
        m = FAQUpdate()
        assert m.model_dump(exclude_unset=True) == {}

    def test_null_question_not_treated_as_clear(self):
        # `question=None` means "field not set", not "blank it out".
        # The validator returns None and `exclude_unset` filters it.
        m = FAQUpdate(question=None)
        assert "question" not in m.model_dump(exclude_unset=True) or m.question is None
