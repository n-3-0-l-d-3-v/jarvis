from datetime import date

from jarvis.vault_briefing import vault_briefing


def test_unconfigured():
    assert vault_briefing(vault="") == {"configured": False}


def test_collects_wall_e_alfred_ultron(tmp_path):
    a = tmp_path / "agents"
    (a / "Wall-E").mkdir(parents=True); (a / "Alfred").mkdir(); (a / "Ultron" / "pending").mkdir(parents=True)
    # Wall-E's real format (walle/report.py render_markdown): `status:` + "- Reason:" lines.
    (a / "Wall-E" / "wall-e-report-2026-09-14.md").write_text(
        "---\ndate: 2026-09-14T04:00:00+00:00\nstatus: degraded\nagent: Wall-E\n---\n\n"
        "**Overall status: DEGRADED**\n- Reason: low disk space: 6.1% free (28 GB)\n")
    (a / "Alfred" / "x.md").write_text("---\npattern_archetype: two_pointers\nnext_due: 2026-09-20\n---\n")
    (a / "Alfred" / "y.md").write_text("---\nnext_due: 2027-01-01\n---\n")
    (a / "Ultron" / "pending" / "n.md").write_text("x")
    r = vault_briefing(str(tmp_path), today=date(2026, 9, 19))
    assert r["wall_e"]["overall_status"] == "degraded"
    assert r["wall_e"]["reasons"] == ["low disk space: 6.1% free (28 GB)"]
    assert [d["topic"] for d in r["alfred_reviews_due"]] == ["two_pointers"]
    assert r["ultron_pending_review"] == 1
