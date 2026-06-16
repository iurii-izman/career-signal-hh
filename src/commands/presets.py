from __future__ import annotations

import argparse

import yaml
from rich.console import Console
from rich.table import Table

from ..search_presets import get_preset, list_presets

console = Console()


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
        any_kw = include.get("any", [])
        title_kw = include.get("title", [])
        all_kw = include.get("all", [])
        lines = []
        if any_kw:
            lines.append(f"  any: {', '.join(any_kw)}")
        if title_kw:
            lines.append(f"  title: {', '.join(title_kw)}")
        if all_kw:
            lines.append(f"  all: {', '.join(all_kw)}")
        table.add_row("Include", "\n".join(lines) if lines else "-")

    exclude = preset.get("exclude", {})
    if exclude:
        any_kw = exclude.get("any", [])
        title_kw = exclude.get("title", [])
        lines = []
        if any_kw:
            lines.append(f"  any: {', '.join(any_kw)}")
        if title_kw:
            lines.append(f"  title: {', '.join(title_kw)}")
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
