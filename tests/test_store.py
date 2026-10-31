import json
from datetime import UTC, datetime, timedelta

from changerisk import engine, store
from changerisk.store import ReportStore

from .test_engine import risky_branch, seeded


def report_for(repo):
    seeded(repo)
    risky_branch(repo)
    return engine.analyze(repo.root, base="main", head="feature/speedup", use_history=False)


def test_save_assigns_id_stamp_and_ignores_itself(repo):
    rep = report_for(repo)
    s = ReportStore(repo.root)
    when = datetime(2026, 9, 3, 14, 5, 9, tzinfo=UTC)
    rid = s.save(rep, created=when)
    assert rid.startswith("20260903-140509-") and rep.id == rid
    assert rep.generated_at == "2026-09-03T14:05:09+00:00"
    assert (repo.root / ".changerisk" / ".gitignore").exists()


def test_same_second_saves_do_not_collide(repo):
    rep = report_for(repo)
    s = ReportStore(repo.root)
    when = datetime(2026, 1, 1, tzinfo=UTC)
    ids = {s.save(rep, created=when) for _ in range(3)}
    assert len(ids) == 3


def test_list_is_newest_first_with_summaries(repo):
    rep = report_for(repo)
    s = ReportStore(repo.root)
    base = datetime(2026, 5, 1, tzinfo=UTC)
    for i in range(3):
        s.save(rep, created=base + timedelta(days=i))
    listing = s.list()
    assert [r["generated_at"][:10] for r in listing] == ["2026-05-03", "2026-05-02", "2026-05-01"]
    first = listing[0]
    assert first["level"] == "critical" and first["gate_failed"] is True and len(first["top"]) == 3


def test_corrupt_files_are_skipped(repo):
    rep = report_for(repo)
    s = ReportStore(repo.root)
    s.save(rep)
    (s.dir / "20990101-000000-broken.json").write_text("{not json", encoding="utf-8")
    assert len(s.list()) == 1
    assert s.get("20990101-000000-broken") is None


def test_ids_are_validated(repo):
    s = ReportStore(repo.root)
    for bad in ("../x", "a/b", "", "ab", "x" * 100, ".hidden-file"):
        assert s.get(bad) is None and s.delete(bad) is False


def test_old_reports_are_pruned(repo, monkeypatch):
    monkeypatch.setattr(store, "KEEP", 3)
    rep = report_for(repo)
    s = ReportStore(repo.root)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(6):
        s.save(rep, created=base + timedelta(hours=i))
    assert len(list(s.dir.glob("*.json"))) == 3
    assert s.list()[0]["generated_at"].startswith("2026-01-01T05")


def test_get_round_trips_the_report(repo):
    rep = report_for(repo)
    s = ReportStore(repo.root)
    rid = s.save(rep)
    assert s.get(rid) == json.loads(json.dumps(rep.to_dict()))
