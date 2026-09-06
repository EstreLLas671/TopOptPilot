"""Compress historic activity without exposing model chain-of-thought."""


def compress_events(events: list[dict], keep: int = 20) -> dict:
    historic, recent = events[:-keep], events[-keep:]
    summary = [f"{event['kind']}: {event['title']}" for event in historic]
    return {"summary": summary, "recent": recent}

