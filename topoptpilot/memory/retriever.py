from __future__ import annotations


def retrieve_events(events: list[dict], query: str, limit: int = 8) -> list[dict]:
    terms = {term.lower() for term in query.split() if len(term) > 1}
    ranked = []
    for event in events:
        haystack = f"{event.get('title', '')} {event.get('body', '')}".lower()
        score = sum(term in haystack for term in terms)
        if score:
            ranked.append((score, event.get("id", 0), event))
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:limit]]

