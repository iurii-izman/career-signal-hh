from __future__ import annotations

import sqlite3
from argparse import Namespace
from pathlib import Path

from rich.console import Console

from src.commands import doctor, profiles, sample


def _record_console(monkeypatch, target_module) -> Console:
    output = Console(record=True, width=160)
    monkeypatch.setattr(target_module, "console", output)
    return output


def test_doctor_does_not_fail_without_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HH_AUTH_MODE", raising=False)
    monkeypatch.delenv("HH_APP_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("DB_PATH", "data/test.sqlite")
    (tmp_path / ".env.example").write_text("", encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    (config / "search_profiles.yaml").write_text(
        "profiles:\n  demo:\n    enabled: true\n    queries: [python]\n",
        encoding="utf-8",
    )
    (config / "scoring_rules.yaml").write_text(
        "profiles: {}\nrisks: {}\n", encoding="utf-8"
    )
    output = _record_console(monkeypatch, doctor)

    assert doctor.command_doctor(Namespace()) == 0
    rendered = output.export_text()
    assert ".env" in rendered
    assert "WARN" in rendered
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "exports").is_dir()


def test_profiles_reads_yaml(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "search_profiles.yaml").write_text(
        """
profiles:
  demo_profile:
    enabled: true
    queries: [python, automation, integration, api]
    areas: [1, 2]
    params:
      schedule: [remote]
      experience: [between3And6]
""".strip(),
        encoding="utf-8",
    )
    output = _record_console(monkeypatch, profiles)

    assert profiles.command_profiles(Namespace()) == 0
    rendered = output.export_text()
    assert "demo_profile" in rendered
    assert "remote" in rendered
    assert "python | automation | integration" in rendered


def test_sample_export_creates_vacancies_and_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", "data/sample.sqlite")
    config = tmp_path / "config"
    config.mkdir()
    (config / "scoring_rules.yaml").write_text(
        """
profiles:
  ai_automation:
    keywords:
      python: 20
      rag: 20
      integration: 15
      automation: 15
  bitrix_1c:
    keywords:
      битрикс24: 25
      crm: 15
      1с: 25
      bpmn: 15
risks:
  sales_only:
    keywords: ["менеджер по продажам", "холодные звонки"]
    penalty: 35
""".strip(),
        encoding="utf-8",
    )
    _record_console(monkeypatch, sample)

    # sample-export now uses its own DB by default
    assert sample.command_sample_export(Namespace(db=None)) == 0
    assert sample.command_sample_export(Namespace(db=None)) == 0
    with sqlite3.connect("data/sample_vacancies.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0] == 6
        assert connection.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 6
        reviews = dict(
            connection.execute(
                "SELECT vacancy_id, status FROM vacancy_reviews"
            ).fetchall()
        )
        assert reviews == {
            "sample-ai-llm": "interesting",
            "sample-ai-pm": "maybe",
            "sample-bitrix": "applied",
            "sample-low": "rejected",
        }
    assert (tmp_path / "exports" / "vacancies_report.html").is_file()
    assert (tmp_path / "exports" / "vacancies.csv").is_file()
    assert (tmp_path / "exports" / "vacancies.jsonl").is_file()
