"""Bounding identities: no client can make a key longer than the limit."""

from tokenguard.identity import DEFAULT_MAX_KEY_LENGTH, bound_identity


def test_short_identities_are_untouched():
    assert bound_identity("user:42") == "user:42"
    exact = "x" * DEFAULT_MAX_KEY_LENGTH
    assert bound_identity(exact) == exact


def test_long_identities_become_a_fixed_size_stand_in():
    long = "ip:1.2.3.4:" + "a" * 5000
    bounded = bound_identity(long)
    assert len(bounded) == 34 and bounded.startswith("h:")


def test_the_stand_in_is_stable_and_distinguishes_identities():
    a, b = "a" * 500, "a" * 499 + "b"
    assert bound_identity(a) == bound_identity(a)
    assert bound_identity(a) != bound_identity(b)


def test_the_limit_is_adjustable():
    assert bound_identity("abcdef", 5).startswith("h:")
    assert bound_identity("abcde", 5) == "abcde"


def test_odd_characters_do_not_break_hashing():
    assert bound_identity("\ud800" * 300).startswith("h:")  # a lone surrogate
