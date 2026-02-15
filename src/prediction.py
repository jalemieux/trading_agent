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


def parse_prediction(raw: str, current_price: float) -> Prediction | None:
    """Parse an LLM response into a Prediction. Returns None on failure."""
    # Strip markdown code blocks if present
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    try:
        data = json.loads(stripped)
        return Prediction(
            target_price=float(data["target_price"]),
            timeframe_minutes=int(data["timeframe_minutes"]),
            reasoning=str(data["reasoning"]),
            current_price=current_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("Failed to parse prediction response: %s", raw[:200])
        return None
