from alexa_mcp_server.ids import new_ulid
from alexa_mcp_server.matching import fuzzy_score, tiered_match


def _item(text, subject=None, created_at="2026-10-01T00:00:00+00:00"):
    return {"sk": f"MEM#{new_ulid()}", "text": text, "subject": subject, "created_at": created_at}


def test_exact_phrase_wins_over_fuzzy():
    items = [_item("Reply to Sam about the invoice"), _item("The report is due Friday")]
    resolution, hits = tiered_match("report", items)
    assert resolution == "exact"
    assert [h.item["text"] for h in hits] == ["The report is due Friday"]


def test_alias_resolves_to_person_subject():
    items = [_item("Send the Q3 deck", subject="Priya"), _item("Book the dentist")]
    resolution, hits = tiered_match("what did I promise my boss", items, {"Priya": ["my boss", "P"]})
    assert resolution == "alias"
    assert hits[0].item["subject"] == "Priya"


def test_fuzzy_tolerates_typos():
    items = [_item("Book the dentist appointment")]
    resolution, hits = tiered_match("dentst apointment", items)
    assert resolution == "fuzzy"
    assert hits


def test_no_match():
    assert tiered_match("volcano", [_item("Book the dentist")]) == (None, [])
    assert tiered_match("   ", [_item("Book the dentist")]) == (None, [])


def test_exact_hits_newest_first():
    old = _item("call mom", created_at="2026-10-01T00:00:00+00:00")
    new = _item("call mom back", created_at="2026-10-03T00:00:00+00:00")
    _, hits = tiered_match("call mom", [old, new])
    assert [h.item["text"] for h in hits] == ["call mom back", "call mom"]


def test_fuzzy_score_word_coverage():
    assert fuzzy_score("budget email", "Drafting the budget email for finance") == 1.0
    assert fuzzy_score("taxes", "Book the dentist") < 0.6


def test_ulids_sort_in_creation_order():
    ids = [new_ulid() for _ in range(1000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 1000
