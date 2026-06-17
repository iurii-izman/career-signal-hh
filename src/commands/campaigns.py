"""Campaign commands — multi-candidate workflow management."""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..campaigns import (
    get_campaign,
    get_campaign_presets,
    get_candidate_profile_name,
    list_enabled_campaigns,
)
from ..storage import Storage

console = Console()


def _storage() -> Storage:
    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


# ── list ─────────────────────────────────────────────────────────────────────


def command_campaigns_list(_: argparse.Namespace) -> int:
    """List all enabled campaigns."""
    campaigns = list_enabled_campaigns()
    if not campaigns:
        console.print("[yellow]No campaigns found in config/campaigns.yaml[/yellow]")
        console.print("[dim]Create config/campaigns.yaml to define campaigns.[/dim]")
        return 0

    table = Table(title="Campaigns")
    table.add_column("Name")
    table.add_column("Profile")
    table.add_column("Presets")
    table.add_column("Lang")
    table.add_column("Min Score")
    table.add_column("Description")

    for c in campaigns:
        table.add_row(
            c["_name"],
            c.get("candidate_profile", "default"),
            ", ".join(c.get("presets", [])),
            c.get("default_lang", "ru"),
            str(c.get("min_score", 0)),
            c.get("description", "")[:60],
        )

    console.print(table)
    return 0


# ── show ─────────────────────────────────────────────────────────────────────


def command_campaigns_show(args: argparse.Namespace) -> int:
    """Show details for a single campaign."""
    campaign = get_campaign(args.name)
    if campaign is None:
        console.print(f"[red]Campaign '{args.name}' not found.[/red]")
        return 1

    console.print(f"\n[bold cyan]{campaign['_name']}[/bold cyan]")
    console.print(f"  Description: {campaign.get('description', '-')}")
    console.print(f"  Candidate profile: {campaign.get('candidate_profile', 'default')}")
    console.print(f"  Presets: {', '.join(campaign.get('presets', []))}")
    console.print(f"  Default lang: {campaign.get('default_lang', 'ru')}")
    console.print(f"  Min score: {campaign.get('min_score', 0)}")
    console.print(f"  Apply template: {campaign.get('apply_template', 'default')}")

    # Show resolved presets
    presets = get_campaign_presets(campaign)
    if presets:
        console.print(f"\n  Resolved {len(presets)} preset(s):")
        for p in presets:
            terms = p.get("search_terms", [])
            console.print(f"    • {p.get('_name', '?')} — {len(terms)} terms")
    else:
        console.print("\n  [yellow]No presets resolved — check preset names.[/yellow]")

    return 0


# ── daily ────────────────────────────────────────────────────────────────────


def command_campaigns_daily(args: argparse.Namespace) -> int:
    """Run daily workflow for a campaign."""
    campaign = get_campaign(args.name)
    if campaign is None:
        console.print(f"[red]Campaign '{args.name}' not found.[/red]")
        return 1

    preset_names = campaign.get("presets", [])
    if not preset_names:
        console.print(f"[yellow]Campaign '{args.name}' has no presets.[/yellow]")
        return 0

    console.print(f"\n[bold cyan]Campaign: {args.name}[/bold cyan]")
    console.print(f"  Profile: {campaign.get('candidate_profile', 'default')}")
    console.print(f"  Presets: {', '.join(preset_names)}")

    for pname in preset_names:
        console.print(f"\n[bold]→ Preset: {pname}[/bold]")

        # Run autopilot daily for this preset
        from .autopilot import command_autopilot_daily

        rc = command_autopilot_daily(
            argparse.Namespace(
                mode="normal",
                preset=pname,
                skip_auth_check=getattr(args, "skip_auth_check", False),
                skip_search=getattr(args, "skip_search", False),
                skip_rescore=getattr(args, "skip_rescore", False),
                skip_export=getattr(args, "skip_export", False),
                skip_queue=getattr(args, "skip_queue", False),
                queue_limit=20,
                min_score=campaign.get("min_score", 70),
                backup_first=True,
                allow_deep=False,
                ignore_doctor_warnings=False,
                yes=False,
            )
        )
        if rc != 0:
            console.print(f"[yellow]Preset '{pname}' completed with warnings.[/yellow]")

    # Show campaign queue
    console.print(f"\n[bold]Campaign Queue (min score {campaign.get('min_score', 70)}):[/bold]")
    from .review import command_review_queue

    command_review_queue(
        argparse.Namespace(
            decision=None,
            min_score=campaign.get("min_score", 70),
            preset=preset_names[0] if len(preset_names) == 1 else None,
            profile=None,
            status=None,
            limit=15,
            remote_only=False,
            with_salary=False,
            hide_risk=False,
            new_only=False,
            dedupe=False,
        )
    )

    console.print(f"\n[bold green]Campaign {args.name} complete![/bold green]")
    console.print(f"[dim]Next: campaigns apply-pack {args.name} --top 5[/dim]")
    return 0


# ── queue ────────────────────────────────────────────────────────────────────


def command_campaigns_queue(args: argparse.Namespace) -> int:
    """Show queue filtered by campaign presets."""
    campaign = get_campaign(args.name)
    if campaign is None:
        console.print(f"[red]Campaign '{args.name}' not found.[/red]")
        return 1

    preset_names = campaign.get("presets", [])
    min_score = campaign.get("min_score", 0)

    from .review import command_review_queue

    for pname in preset_names:
        console.print(f"\n[bold cyan]Queue for {pname}:[/bold cyan]")
        command_review_queue(
            argparse.Namespace(
                decision=None,
                min_score=min_score,
                preset=pname,
                profile=None,
                status=None,
                limit=15,
                remote_only=False,
                with_salary=False,
                hide_risk=False,
                new_only=False,
                dedupe=False,
            )
        )
    return 0


# ── apply-pack ───────────────────────────────────────────────────────────────


def command_campaigns_apply_pack(args: argparse.Namespace) -> int:
    """Generate apply packs using campaign's candidate profile."""
    campaign = get_campaign(args.name)
    if campaign is None:
        console.print(f"[red]Campaign '{args.name}' not found.[/red]")
        return 1

    profile = get_candidate_profile_name(campaign)
    lang = campaign.get("default_lang", "ru")
    template = campaign.get("apply_template")
    min_score = campaign.get("min_score", 0)
    top = args.top or 5

    console.print(f"\n[bold cyan]Apply Pack — {args.name}[/bold cyan]")
    console.print(f"  Candidate profile: {profile}")
    console.print(f"  Language: {lang}")
    console.print(f"  Min score: {min_score}")

    # Temporarily override _pick_profile to use campaign's profile
    import src.commands.apply_pack as ap_mod

    original_pick = ap_mod._pick_profile
    ap_mod._pick_profile = lambda preset_name: profile
    try:
        from .apply_pack import command_apply_pack

        command_apply_pack(
            argparse.Namespace(
                vacancy_id=None,
                top=top,
                limit=None,
                decision="strong_match",
                preset=None,
                min_score=min_score,
                lang=lang,
                format="both",
                style="medium",
                template=template,
                save_review=True,
                overwrite=False,
            )
        )
    finally:
        ap_mod._pick_profile = original_pick

    console.print(f"\n[bold green]Apply packs generated for {args.name}![/bold green]")
    return 0
