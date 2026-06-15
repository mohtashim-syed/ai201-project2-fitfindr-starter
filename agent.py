"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract a description, size, and max_price from a free-text query using
    plain regex (no LLM) — fast, deterministic, and easy to test.

    Returns a dict: {"description": str, "size": str | None, "max_price": float | None}
    """
    q = query.lower()

    # max_price: "under $30", "$30", "below 30", "30 dollars" → first number found.
    price = None
    m = re.search(r"(?:under|below|less than|max|up to|<|\$)\s*\$?\s*(\d+(?:\.\d+)?)", q)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:dollars|bucks)", q)
    if m:
        price = float(m.group(1))

    # size: prefer an explicit "size X"; else a "US 8"-style shoe size.
    size = None
    sm = re.search(r"\bsize\s+([a-z0-9/.]+)", q)
    if sm:
        size = sm.group(1).upper()
    else:
        sm = re.search(r"\b(us\s*\d+(?:\.\d+)?)\b", q)
        if sm:
            size = sm.group(1).upper()

    # description: strip the price/size phrases so only keywords remain.
    desc = query
    desc = re.sub(r"(?i)\b(?:under|below|less than|max|up to)\s*\$?\s*\d+(?:\.\d+)?", "", desc)
    desc = re.sub(r"\$\s*\d+(?:\.\d+)?", "", desc)
    desc = re.sub(r"(?i)\b\d+(?:\.\d+)?\s*(?:dollars|bucks)\b", "", desc)
    desc = re.sub(r"(?i)\bin\s+size\s+[a-z0-9/.]+", "", desc)
    desc = re.sub(r"(?i)\bsize\s+[a-z0-9/.]+", "", desc)
    desc = re.sub(r"(?i)\bus\s*\d+(?:\.\d+)?\b", "", desc)
    desc = re.sub(r"\s+", " ", desc).strip(" ,.")

    return {"description": desc, "size": size, "max_price": price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the query into search parameters (regex, no LLM).
    parsed = _parse_query(query)
    session["parsed"] = parsed

    # Step 3: search the listings.
    results = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )
    session["search_results"] = results

    # Step 3 guard — Branch A: nothing matched. Set a specific, actionable
    # error and return EARLY. Do not call the styling tools with empty input.
    if not results:
        size_txt = parsed["size"] or "any"
        price_txt = f"${parsed['max_price']:.0f}" if parsed["max_price"] is not None else "any"
        session["error"] = (
            f"No listings matched '{parsed['description']}' "
            f"(size={size_txt}, under {price_txt}). "
            "Try removing the size filter, raising your budget, or using broader keywords."
        )
        return session

    # Step 4: Branch B — select the top-ranked result for the rest of the flow.
    session["selected_item"] = results[0]

    # Step 5: suggest an outfit (handles an empty wardrobe internally).
    session["outfit_suggestion"] = suggest_outfit(
        new_item=session["selected_item"],
        wardrobe=wardrobe,
    )

    # Step 6: create a shareable fit card (guards empty outfit internally).
    session["fit_card"] = create_fit_card(
        outfit=session["outfit_suggestion"],
        new_item=session["selected_item"],
    )

    # Step 7: done — all fields populated, error stays None.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
