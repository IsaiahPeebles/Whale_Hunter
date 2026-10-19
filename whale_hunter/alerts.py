"""Alert dedupe/storage and terminal formatting (CONTEXT §16, §33)."""
from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from . import db

console = Console()
COLORS = {"EXTREME WHALE ACTIVITY": "bold red", "WHALE ACTIVITY": "red",
          "UNUSUAL": "yellow", "ELEVATED": "cyan", "WALLET HIGH": "bold magenta", "WALLET NOTABLE": "magenta"}


def handle(conn, alert, cfg):
    """Store (and maybe print) an alert unless it repeats a recent one. Returns the alert id or None."""
    if alert["score"] < alert.get("store_threshold", cfg["store_threshold"]):
        return None
    prev = db.last_alert(conn, alert["platform"], alert["market_id"], alert["direction"],
                         alert.get("kind", "market"), alert.get("wallet"))
    if prev and alert["ts"] - prev["ts"] < cfg["alert_cooldown_minutes"] * 60 \
            and alert["score"] < prev["score"] + cfg["rescore_delta"]:
        return None
    alert_id = db.insert_alert(conn, alert)
    # Weak-baseline alerts are kept for the dashboard but not printed, to keep the terminal signal-rich.
    if alert["score"] >= cfg["print_threshold"] and \
            alert["evidence"]["baseline"]["trades"] >= cfg["min_baseline_trades"]:
        console.print(render(alert))
    return alert_id


def render(a):
    e = a["evidence"]
    lines = [
        f"[bold]Market:[/bold] {a['title']}",
        f"[bold]Platform:[/bold] {a['platform'].title()}    "
        f"[bold]Direction:[/bold] {a['direction']} ({e['direction_label']})",
        f"[bold]Detected:[/bold] {e['detected']}",
        "[bold]Why unusual:[/bold]",
        *[f"  • {w}" for w in e["why"]],
    ]
    if e["notes"]:
        lines += ["[bold]Participants:[/bold]", *[f"  • {n}" for n in e["notes"]]]
    if e["context"]:
        lines += ["[bold]Context / possible benign explanations:[/bold]",
                  *[f"  • {c}" for c in e["context"]]]
    lines.append(f"[bold]Confidence:[/bold] {a['confidence']} — {'; '.join(e['confidence_reasons'])}")
    if e.get("url"):
        lines.append(f"[dim]{e['url']}[/dim]")
    lines.append("[dim]Describes observed market behavior only; it does not establish intent "
                 "or private information.[/dim]")
    when = datetime.fromtimestamp(a["ts"]).strftime("%H:%M:%S")
    return Panel("\n".join(lines), title=f"{a['headline']}  [{when}]",
                 border_style=COLORS.get(a.get("color") or a["severity"], "white"), expand=False)
