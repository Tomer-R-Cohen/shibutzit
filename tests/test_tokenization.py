from backend.llm.tokenization import TokenMap


def test_token_for_is_stable_and_reversible():
    tm = TokenMap()
    t1 = tm.token_for(42)
    t2 = tm.token_for(42)
    assert t1 == t2
    assert tm.id_for(t1) == 42


def test_token_is_not_derived_from_the_raw_id():
    # A derived token (e.g. f"STUDENT_{id}") would be trivially reversible
    # by anyone without the session's private mapping. Confirm two fresh
    # TokenMaps produce different tokens for the same id -- proving it's
    # randomly generated, not a formula. (Checking a substring like "42"
    # isn't a reliable test here: a random hex suffix can coincidentally
    # contain it.)
    t1 = TokenMap().token_for(42)
    t2 = TokenMap().token_for(42)
    assert t1 != t2
    assert t1 != "STUDENT_42"
    assert t2 != "STUDENT_42"


def test_ensure_all_creates_a_unique_token_per_id():
    tm = TokenMap()
    tm.ensure_all([1, 2, 3])
    assert len(tm.id_to_token) == 3
    assert len(set(tm.id_to_token.values())) == 3


def test_id_for_unknown_token_returns_none():
    tm = TokenMap()
    assert tm.id_for("STUDENT_nope") is None
