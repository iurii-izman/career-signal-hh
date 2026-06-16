from __future__ import annotations

import re
from difflib import SequenceMatcher

LEGAL_SUFFIXES = [
    "ооо",
    "ооо",
    "ип",
    "ао",
    "зао",
    "пао",
    "нао",
    "llc",
    "ltd",
    "inc",
    "corp",
    "corporation",
    "gmbh",
    "srl",
    "sa",
    "sas",
    "llp",
    "plc",
    "pty ltd",
    "bv",
    "nv",
    "ab",
    "kk",
]


def normalize_employer_name(name: str | None) -> str:
    """Normalize employer name for deduplication."""
    if not name:
        return ""
    n = name.strip().lower()
    # Remove legal suffixes
    n = re.sub(r"[.,;:()\[\]{}«»" "'']", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    # Remove known suffixes if they appear at the end
    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        if n.endswith(" " + suffix):
            n = n[: -(len(suffix) + 1)].strip()
        elif n.endswith(" " + suffix + "."):
            n = n[: -(len(suffix) + 2)].strip()
    # Collapse multiple spaces
    n = re.sub(r"\s+", " ", n).strip()
    return n


def normalize_title(title: str | None) -> str:
    """Normalize vacancy title for similarity comparison."""
    if not title:
        return ""
    t = title.strip().lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Remove common prefixes/suffixes
    for prefix in ["senior ", "junior ", "middle ", "lead ", "principal ", "staff "]:
        if t.startswith(prefix):
            t = t[len(prefix) :]
    for suffix in [" senior", " junior", " middle", " lead"]:
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return t.strip()


def title_similarity(a: str, b: str) -> float:
    """Return similarity ratio between two normalized titles."""
    return SequenceMatcher(None, a, b).ratio()


def find_duplicates(
    vacancies: list[dict],
    *,
    url_threshold: float = 1.0,
    title_threshold: float = 0.85,
) -> list[dict]:
    """Find duplicate vacancy groups.

    Returns list of clusters, each with cluster_id, vacancies, reason, score.
    """
    clusters: list[dict] = []
    seen: set[str] = set()
    used: set[str] = set()

    # Group by URL (exact)
    by_url: dict[str, list[dict]] = {}
    for v in vacancies:
        url = (v.get("alternate_url") or "").strip()
        if url:
            by_url.setdefault(url, []).append(v)

    for url, group in by_url.items():
        if len(group) > 1:
            ids = [v["id"] for v in group]
            cid = f"url_{hash(url) & 0xFFFF:04x}"
            clusters.append(
                {
                    "cluster_id": cid,
                    "vacancy_ids": ids,
                    "reason": "same_url",
                    "similarity": 1.0,
                    "vacancies": group,
                }
            )
            used.update(ids)

    # Group by normalized employer + title similarity
    remaining = [v for v in vacancies if v["id"] not in used]
    for i, v1 in enumerate(remaining):
        if v1["id"] in used:
            continue
        emp1 = normalize_employer_name(v1.get("employer_name"))
        title1 = normalize_title(v1.get("name"))
        group = [v1]
        for v2 in remaining[i + 1 :]:
            if v2["id"] in used:
                continue
            emp2 = normalize_employer_name(v2.get("employer_name"))
            if emp1 and emp2 and emp1 == emp2:
                title2 = normalize_title(v2.get("name"))
                sim = title_similarity(title1, title2)
                if sim >= title_threshold:
                    group.append(v2)
                    used.add(v2["id"])
        if len(group) > 1:
            used.add(v1["id"])
            ids = [v["id"] for v in group]
            cid = f"emp_{hash(emp1) & 0xFFFF:04x}"
            clusters.append(
                {
                    "cluster_id": cid,
                    "vacancy_ids": ids,
                    "reason": "same_employer_similar_title",
                    "similarity": title_threshold,
                    "vacancies": group,
                }
            )

    return clusters
