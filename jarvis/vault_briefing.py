"""Read-only briefing data from the shared vault ($VAULT_PATH/agents/*)."""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional


def _fm(text: str) -> dict:
    m = re.match(r"\A---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def vault_briefing(vault: Optional[str] = None, today: Optional[date] = None) -> dict:
    if vault is None:
        vault = os.environ.get("VAULT_PATH")
    if not vault or not Path(vault).is_dir():
        return {"configured": False}
    today = today or date.today()
    agents = Path(vault) / "agents"
    out: dict = {"configured": True}

    reports = sorted((agents / "Wall-E").glob("wall-e-report-*.md"))
    if reports:
        fm = _fm(reports[-1].read_text(encoding="utf-8"))
        out["wall_e"] = {"report": reports[-1].name, "overall_status": fm.get("overall_status", "unknown")}

    due = []
    horizon = today + timedelta(days=3)
    for p in (agents / "Alfred").glob("*.md"):
        fm = _fm(p.read_text(encoding="utf-8"))
        try:
            nd = date.fromisoformat(fm.get("next_due", ""))
        except ValueError:
            continue
        if nd <= horizon:
            due.append({"topic": fm.get("pattern_archetype", p.stem), "next_due": nd.isoformat()})
    out["alfred_reviews_due"] = sorted(due, key=lambda d: d["next_due"])

    findings = list((agents / "Ultron" / "pending").glob("*.md"))
    out["ultron_pending_review"] = len(findings)
    return out
