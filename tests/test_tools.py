"""
Tests for the three FitFindr tools — at least one test per failure mode.

Run from the project root with:
    pytest tests/

The search_listings tests are fully deterministic (no network). The two LLM
tools are tested for their non-LLM failure modes (empty wardrobe / empty outfit);
the empty-wardrobe test makes a real Groq call and is skipped if no key is set.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

_HAS_KEY = bool(os.environ.get("GROQ_API_KEY"))


# ── search_listings ─────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    # every result carries the full listing schema
    assert all("title" in item and "price" in item for item in results)


def test_search_empty_results():
    # Impossible combination → empty list, no exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter():
    # "M" should match sizes like "S/M" via case-insensitive substring matching.
    results = search_listings("graphic tee", size="M", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    # A precise multi-keyword query should rank an actual graphic tee first.
    results = search_listings("vintage graphic tee", size=None, max_price=30)
    assert results, "expected at least one match"
    assert results[0]["category"] == "tops"


# ── create_fit_card (failure mode: empty outfit — no LLM call) ───────────────

def test_create_fit_card_empty_outfit():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    msg = create_fit_card("", item)
    assert isinstance(msg, str) and msg.strip()
    assert "without an outfit" in msg.lower()


def test_create_fit_card_whitespace_outfit():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    msg = create_fit_card("   \n  ", item)
    assert "without an outfit" in msg.lower()


# ── suggest_outfit (failure mode: empty wardrobe — real LLM call) ────────────

@pytest.mark.skipif(not _HAS_KEY, reason="GROQ_API_KEY not set")
def test_suggest_outfit_empty_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    advice = suggest_outfit(item, get_empty_wardrobe())
    # Must return useful, non-empty general advice rather than crash / empty string.
    assert isinstance(advice, str)
    assert len(advice.strip()) > 0


@pytest.mark.skipif(not _HAS_KEY, reason="GROQ_API_KEY not set")
def test_suggest_outfit_populated_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    advice = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(advice, str)
    assert len(advice.strip()) > 0
