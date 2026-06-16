from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from ..search_presets import get_preset, list_presets, validate_preset

console = Console()

PRESETS_PATH = "config/search_presets.yaml"
BACKUPS_DIR = Path("config/backups")


def _load_raw() -> dict:
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _save_raw(data: dict) -> None:
    Path(PRESETS_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(PRESETS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f, allow_unicode=True, default_flow_style=False, sort_keys=False
        )


def _backup() -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUPS_DIR / f"search_presets_{ts}.yaml"
    if Path(PRESETS_PATH).exists():
        shutil.copy2(PRESETS_PATH, dst)
    return dst


def _ensure_preset(data: dict, name: str) -> dict:
    presets = data.setdefault("presets", {})
    if name not in presets:
        raise ValueError(f"Preset '{name}' not found")
    return presets[name]


def _ensure_include(preset: dict) -> dict:
    if "include" not in preset:
        preset["include"] = {"any": [], "all": [], "title": []}
    return preset["include"]


def _ensure_exclude(preset: dict) -> dict:
    if "exclude" not in preset:
        preset["exclude"] = {"any": [], "title": []}
    return preset["exclude"]


# ---------------------------------------------------------------------------
# Existing commands
# ---------------------------------------------------------------------------


def command_presets_list(_: argparse.Namespace) -> int:
    try:
        presets = list_presets()
    except yaml.YAMLError as exc:
        console.print(f"[red]YAML error: {exc}[/red]")
        return 1
    if not presets:
        console.print("[yellow]No enabled presets found.[/yellow]")
        return 0
    table = Table(title="Search Presets")
    for col in [
        "Name",
        "Enabled",
        "Terms",
        "Remote",
        "Areas",
        "Include",
        "Exclude",
        "Description",
    ]:
        table.add_column(col)
    for p in presets:
        name = p.get("_name", "?")
        terms = len(p.get("search_terms", []))
        remote = "yes" if p.get("remote_only") else "no"
        areas = "all" if not p.get("areas") else str(len(p.get("areas", [])))
        inc = len(p.get("include", {}).get("any", [])) + len(
            p.get("include", {}).get("title", [])
        )
        exc = len(p.get("exclude", {}).get("any", [])) + len(
            p.get("exclude", {}).get("title", [])
        )
        desc = p.get("description", "")[:60]
        table.add_row(
            name,
            "yes" if p.get("enabled") else "no",
            str(terms),
            remote,
            areas,
            str(inc),
            str(exc),
            desc,
        )
    console.print(table)
    return 0


def command_presets_show(args: argparse.Namespace) -> int:
    try:
        preset = get_preset(args.preset_name)
    except yaml.YAMLError as exc:
        console.print(f"[red]YAML error: {exc}[/red]")
        return 1
    if preset is None:
        console.print(f"[red]Preset '{args.preset_name}' not found.[/red]")
        return 1
    table = Table(title=f"Preset: {args.preset_name}")
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Description", preset.get("description", "-"))
    table.add_row("Enabled", str(preset.get("enabled", True)))
    table.add_row("Remote only", str(preset.get("remote_only", True)))
    table.add_row(
        "Areas",
        "all"
        if not preset.get("areas")
        else ", ".join(map(str, preset.get("areas", []))),
    )
    table.add_row("Schedule", ", ".join(preset.get("schedule", [])) or "-")
    table.add_row("Experience", ", ".join(preset.get("experience", [])) or "-")
    search_terms = preset.get("search_terms", [])
    table.add_row(
        "Search terms",
        "\n".join(f"  • {t}" for t in search_terms) if search_terms else "-",
    )
    include = preset.get("include", {})
    if include:
        lines = []
        for k in ("any", "title", "all"):
            vals = include.get(k, [])
            if vals:
                lines.append(f"  {k}: {', '.join(vals)}")
        table.add_row("Include", "\n".join(lines) if lines else "-")
    exclude = preset.get("exclude", {})
    if exclude:
        lines = []
        for k in ("any", "title"):
            vals = exclude.get(k, [])
            if vals:
                lines.append(f"  {k}: {', '.join(vals)}")
        table.add_row("Exclude", "\n".join(lines) if lines else "-")
    boost = preset.get("boost", {})
    if boost:
        lines = []
        for field, rules in boost.items():
            if isinstance(rules, dict):
                for kw, w in rules.items():
                    lines.append(f"  {field}: {kw} (+{w})")
        if lines:
            table.add_row("Boost", "\n".join(lines[:15]))
    penalties = preset.get("penalties", {})
    if penalties:
        lines = []
        for field, rules in penalties.items():
            if isinstance(rules, dict):
                for kw, w in rules.items():
                    lines.append(f"  {field}: {kw} (-{w})")
        if lines:
            table.add_row("Penalties", "\n".join(lines[:15]))
    console.print(table)
    return 0


# ---------------------------------------------------------------------------
# Management commands
# ---------------------------------------------------------------------------


def command_presets_validate(_: argparse.Namespace) -> int:
    try:
        presets = list_presets()
    except yaml.YAMLError as exc:
        console.print(f"[red]YAML error: {exc}[/red]")
        return 1
    errors: list[str] = []
    for p in presets:
        errors.extend(validate_preset(p))
    if errors:
        console.print("[red]Validation errors:[/red]")
        for e in errors:
            console.print(f"  - {e}")
        return 1
    console.print(f"[green]All {len(presets)} presets valid.[/green]")
    return 0


def command_presets_create(args: argparse.Namespace) -> int:
    data = _load_raw()
    presets = data.setdefault("presets", {})
    if args.name in presets and not args.overwrite:
        console.print(
            f"[red]Preset '{args.name}' already exists. Use --overwrite.[/red]"
        )
        return 1
    terms = [t.strip() for t in (args.terms or "").split(",") if t.strip()]
    inc = [k.strip() for k in (args.include or "").split(",") if k.strip()]
    exc = [k.strip() for k in (args.exclude or "").split(",") if k.strip()]
    preset = {
        "enabled": True,
        "description": args.description or f"Preset {args.name}",
        "search_terms": terms,
        "filters": {
            "remote_only": args.remote_only,
            "areas": [],
            "schedule": ["remote"] if args.remote_only else [],
            "experience": [],
        },
        "include": {"any": inc, "all": [], "title": []},
        "exclude": {"any": exc, "title": []},
    }
    presets[args.name] = preset
    _backup()
    _save_raw(data)
    console.print(
        f"[green]Preset '{args.name}' created ({len(terms)} terms, {len(inc)} include, {len(exc)} exclude).[/green]"
    )
    return 0


def command_presets_clone(args: argparse.Namespace) -> int:
    data = _load_raw()
    presets = data.setdefault("presets", {})
    if args.source not in presets:
        console.print(f"[red]Source preset '{args.source}' not found.[/red]")
        return 1
    if args.new_name in presets and not args.overwrite:
        console.print(
            f"[red]Target '{args.new_name}' already exists. Use --overwrite.[/red]"
        )
        return 1
    import copy

    presets[args.new_name] = copy.deepcopy(presets[args.source])
    presets[args.new_name]["description"] = f"Clone of {args.source}"
    _backup()
    _save_raw(data)
    console.print(f"[green]Cloned '{args.source}' → '{args.new_name}'.[/green]")
    return 0


def _modify_list(
    data: dict, name: str, action: str, path: list[str], value: str
) -> int:
    presets = data.setdefault("presets", {})
    if name not in presets:
        console.print(f"[red]Preset '{name}' not found.[/red]")
        return 1
    preset = presets[name]
    current = preset
    for key in path[:-1]:
        current = current.setdefault(key, {})
    lst = current.setdefault(path[-1], [])
    if action == "add":
        if value not in lst:
            lst.append(value)
            verb = "Added"
        else:
            console.print(f"[dim]'{value}' already present, idempotent.[/dim]")
            return 0
    elif action == "remove":
        if value in lst:
            lst.remove(value)
            verb = "Removed"
        else:
            console.print(f"[dim]'{value}' not found, idempotent.[/dim]")
            return 0
    _backup()
    _save_raw(data)
    console.print(f"[green]{verb} '{value}' {'→'.join(path)} in '{name}'.[/green]")
    return 0


def command_presets_add_term(args: argparse.Namespace) -> int:
    return _modify_list(_load_raw(), args.name, "add", ["search_terms"], args.term)


def command_presets_remove_term(args: argparse.Namespace) -> int:
    return _modify_list(_load_raw(), args.name, "remove", ["search_terms"], args.term)


def command_presets_add_include(args: argparse.Namespace) -> int:
    return _modify_list(_load_raw(), args.name, "add", ["include", "any"], args.keyword)


def command_presets_add_exclude(args: argparse.Namespace) -> int:
    return _modify_list(_load_raw(), args.name, "add", ["exclude", "any"], args.keyword)


def command_presets_disable(args: argparse.Namespace) -> int:
    data = _load_raw()
    _ensure_preset(data, args.name)["enabled"] = False
    _backup()
    _save_raw(data)
    console.print(f"[yellow]Preset '{args.name}' disabled.[/yellow]")
    return 0


def command_presets_enable(args: argparse.Namespace) -> int:
    data = _load_raw()
    _ensure_preset(data, args.name)["enabled"] = True
    _backup()
    _save_raw(data)
    console.print(f"[green]Preset '{args.name}' enabled.[/green]")
    return 0


def command_presets_save_adhoc(args: argparse.Namespace) -> int:
    inc = [k.strip() for k in (args.include or "").split(",") if k.strip()]
    exc = [k.strip() for k in (args.exclude or "").split(",") if k.strip()]
    if not inc:
        console.print("[red]--include is required.[/red]")
        return 1
    data = _load_raw()
    presets = data.setdefault("presets", {})
    if args.name in presets and not args.overwrite:
        console.print(
            f"[red]Preset '{args.name}' already exists. Use --overwrite.[/red]"
        )
        return 1
    preset = {
        "enabled": True,
        "description": f"Saved adhoc preset ({len(inc)} include, {len(exc)} exclude)",
        "search_terms": inc[:],
        "filters": {
            "remote_only": args.remote_only,
            "areas": [],
            "schedule": ["remote"] if args.remote_only else [],
            "experience": [],
        },
        "include": {"any": inc, "all": [], "title": []},
        "exclude": {"any": exc, "title": []},
    }
    presets[args.name] = preset
    _backup()
    _save_raw(data)
    console.print(f"[green]Adhoc preset saved as '{args.name}'.[/green]")
    return 0
