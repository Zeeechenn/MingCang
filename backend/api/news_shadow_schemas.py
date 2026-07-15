"""Request contracts owned by the M68 news-shadow API."""
from typing import Literal

from pydantic import BaseModel, Field


class NewsShadowFeedbackCreate(BaseModel):
    category: Literal[
        "stale_evidence",
        "duplicate_evidence",
        "false_event",
        "missing_evidence",
        "wrong_entity_link",
        "wrong_event_class",
        "wrong_sentiment_direction",
        "wrong_materiality",
        "wrong_trigger_threshold",
        "fusion_dilution",
        "unusable_explanation",
        # Compatibility values accepted from early M68 trial rows/clients.
        "bad_attribution",
        "legacy_better",
        "pyramid_better",
        "action_disagreement",
        "other",
    ]
    preferred_path: Literal["legacy", "pyramid", "unclear"] | None = None
    evidence_ref: str | None = Field(default=None, max_length=512)
    note: str | None = Field(default=None, max_length=2000)
