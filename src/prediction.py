import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class Prediction:
    target_price: float
    timeframe_minutes: int
    reasoning: str
    current_price: float
    timestamp: str


def _extract_json(text: str) -> str:
    """Extract the first JSON object from text, handling surrounding prose."""
    # Strip markdown code blocks if present
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text)

    # Try the full text first (already clean JSON)
    text = text.strip()
    if text.startswith("{"):
        return text

    # Find the first { ... } block (handles preamble/postamble text)
    match = re.search(r"\{[^{}]*\}", text)
    if match:
        return match.group(0)

    return text


def parse_prediction(raw: str, current_price: float) -> Prediction | None:
    """Parse an LLM response into a Prediction. Returns None on failure."""
    extracted = _extract_json(raw)

    try:
        data = json.loads(extracted)
        return Prediction(
            target_price=float(data["target_price"]),
            timeframe_minutes=int(data["timeframe_minutes"]),
            reasoning=str(data["reasoning"]),
            current_price=current_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.warning(
            "Failed to parse prediction response (%s: %s)\n  raw (%d chars): %r\n  extracted: %r",
            type(e).__name__, e, len(raw), raw[:500], extracted[:500],
        )
        return None
