from datetime import date

from jarvis.vault_briefing import vault_briefing


def test_unconfigured():
    assert vault_briefing(vault="") == {"configured": False}


def test_collects_wall_e_alfred_ultron(tmp_path):
    a = tmp_path / "agents"
    (a / "Wall-E").mkdir(parents=True); (a / "Alfred").mkdir(); (a / "Ultron" / "pending").mkdir(parents=True)
    (a / "Wall-E" / "wall-e-report-2026-09-14.md").write_text("---\noverall_status: ok\n---\n")
    (a / "Alfred" / "x.md").write_text("---\npattern_archetype: two_pointers\nnext_due: 2026-09-20\n---\n")
    (a / "Alfred" / "y.md").write_text("---\nnext_due: 2027-01-01\n---\n")
    (a / "Ultron" / "pending" / "n.md").write_text("x")
    r = vault_briefing(str(tmp_path), today=date(2026, 9, 19))
    assert r["wall_e"]["overall_status"] == "ok"
    assert [d["topic"] for d in r["alfred_reviews_due"]] == ["two_pointers"]
    assert r["ultron_pending_review"] == 1
