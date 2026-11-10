from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def now(timezone: str = "UTC") -> str:
    """Date et heure courantes au format ISO 8601, dans le fuseau demandé."""
    tz = UTC if timezone.upper() == "UTC" else ZoneInfo(timezone)
    return datetime.now(tz).isoformat()
