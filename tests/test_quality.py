"""Tests for data quality persistence in SQLite."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.data_quality import find_duplicates
from src.models import Vacancy
from src.storage import Storage


def _make_storage(tmp_path: Path) -> Storage:
    db_path = str(tmp_path / "test_quality.sqlite")
    return Storage(db_path)


def _make_vacancy(vid: str, name: str, employer: str, url: str, score: int = 50) -> Vacancy:
    now = datetime.now(timezone.utc).isoformat()
    return Vacancy(
        id=vid,
        name=name,
        employer_name=employer,
        alternate_url=url,
        raw_json="{}",
        first_seen_at=now,
        last_seen_at=now,
    )


# ── Clusters saved to SQLite ────────────────────────────────────────────────


def test_quality_cluster_writes_vacancy_clusters(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    v1 = _make_vacancy("dup-1", "Python Developer", "Acme Corp", "https://hh.ru/1", 80)
    v2 = _make_vacancy("dup-2", "Python Developer", "Acme Corp", "https://hh.ru/1", 60)
    v3 = _make_vacancy("uniq-1", "Java Dev", "Other Inc", "https://hh.ru/2", 70)

    storage.upsert_vacancy(v1)
    storage.upsert_vacancy(v2)
    storage.upsert_vacancy(v3)

    rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(rows)

    assert len(clusters) >= 1, "Should find at least one URL-based duplicate"

    storage.replace_vacancy_clusters(clusters)

    # Verify DB state
    assert storage.count_clusters() == len(clusters)
    assert storage.count_duplicate_vacancies() == sum(len(c["vacancy_ids"]) for c in clusters)

    # get_cluster_for_vacancy
    info = storage.get_cluster_for_vacancy("dup-1")
    assert info is not None
    assert info["cluster_id"]
    assert info["cluster_reason"] == "same_url"

    # Non-duplicate has no cluster
    assert storage.get_cluster_for_vacancy("uniq-1") is None

    # list_clusters
    db_clusters = storage.list_clusters()
    assert len(db_clusters) == len(clusters)


def test_employer_aliases_saved(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    aliases = {
        "yandex": ["Yandex LLC", "Яндекс", "Yandex"],
        "sber": ["Сбербанк", "Sberbank", "ПАО Сбербанк"],
    }
    storage.replace_employer_aliases(aliases)

    assert storage.count_employer_aliases() == 2

    db_aliases = storage.list_employer_aliases()
    assert len(db_aliases) == 2

    # Check that the canonical names are present
    canonicals = {a["canonical_name"] for a in db_aliases}
    assert "yandex" in canonicals
    assert "sber" in canonicals


# ── Repeated quality cluster is idempotent ──────────────────────────────────


def test_repeated_quality_cluster_is_idempotent(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    v1 = _make_vacancy("a1", "Dev", "Corp", "https://hh.ru/x", 90)
    v2 = _make_vacancy("a2", "Dev", "Corp", "https://hh.ru/x", 70)
    storage.upsert_vacancy(v1)
    storage.upsert_vacancy(v2)

    rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(rows)

    # First write
    storage.replace_vacancy_clusters(clusters)
    first_count = storage.count_clusters()

    # Second write with same data — must not duplicate rows
    storage.replace_vacancy_clusters(clusters)
    second_count = storage.count_clusters()

    assert first_count == second_count
    assert storage.count_duplicate_vacancies() == 2  # a1 + a2


# ── Review queue dedupe ─────────────────────────────────────────────────────


def test_dedupe_hides_lower_score_duplicate(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    now = datetime.now(timezone.utc).isoformat()

    v1 = _make_vacancy("d1", "Senior Dev", "Acme", "https://hh.ru/d1", 85)
    v2 = _make_vacancy("d2", "Senior Dev", "Acme", "https://hh.ru/d1", 60)
    v3 = _make_vacancy("u1", "Other Role", "Other", "https://hh.ru/u1", 70)

    storage.upsert_vacancy(v1)
    storage.upsert_vacancy(v2)
    storage.upsert_vacancy(v3)

    # Create a score for each (required for queue to work properly)
    from src.models import ScoreResult

    storage.upsert_score(
        ScoreResult(
            vacancy_id="d1",
            total_score=85,
            ai_automation_score=40,
            bitrix_1c_score=45,
            best_profile="ai_automation",
            scored_at=now,
        )
    )
    storage.upsert_score(
        ScoreResult(
            vacancy_id="d2",
            total_score=60,
            ai_automation_score=30,
            bitrix_1c_score=30,
            best_profile="ai_automation",
            scored_at=now,
        )
    )
    storage.upsert_score(
        ScoreResult(
            vacancy_id="u1",
            total_score=70,
            ai_automation_score=35,
            bitrix_1c_score=35,
            best_profile="ai_automation",
            scored_at=now,
        )
    )

    # Create clusters
    rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(rows)
    storage.replace_vacancy_clusters(clusters)

    # Full queue
    full = storage.list_queue(min_score=0, limit=50)
    assert len(full) >= 3

    # Dedupe logic
    from src.commands.review import _dedupe_queue

    deduped = _dedupe_queue(storage, full)

    # d1 (score 85) should be kept, d2 (score 60) should be hidden
    deduped_ids = {r["id"] for r in deduped}
    assert "d1" in deduped_ids, "Best duplicate should be kept"
    assert "d2" not in deduped_ids, "Lower-score duplicate should be hidden"
    assert "u1" in deduped_ids, "Non-duplicate must pass through"


# ── Export includes cluster_id ──────────────────────────────────────────────


def test_export_rows_include_cluster_id(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    v1 = _make_vacancy("e1", "Role", "Corp", "https://hh.ru/e1", 90)
    v2 = _make_vacancy("e2", "Role", "Corp", "https://hh.ru/e1", 70)
    storage.upsert_vacancy(v1)
    storage.upsert_vacancy(v2)

    rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(rows)
    storage.replace_vacancy_clusters(clusters)

    # get_clusters_for_vacancies should return cluster info
    ids = [r["id"] for r in rows]
    cmap = storage.get_clusters_for_vacancies(ids)

    for vid in ["e1", "e2"]:
        assert vid in cmap, f"{vid} should have cluster info"
        assert "cluster_id" in cmap[vid]
        assert "cluster_reason" in cmap[vid]


# ── Cockpit shows cluster count ─────────────────────────────────────────────


def test_cockpit_shows_cluster_count(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    v1 = _make_vacancy("c1", "Dev", "Corp", "https://hh.ru/c1")
    v2 = _make_vacancy("c2", "Dev", "Corp", "https://hh.ru/c1")
    storage.upsert_vacancy(v1)
    storage.upsert_vacancy(v2)

    rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(rows)
    storage.replace_vacancy_clusters(clusters)

    assert storage.count_clusters() >= 1
    assert storage.count_duplicate_vacancies() == 2
