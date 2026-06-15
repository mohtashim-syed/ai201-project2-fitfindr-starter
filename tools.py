"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

from __future__ import annotations  # allow `str | None` hints on Python 3.9

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# LLM model used by the two generative tools.
_MODEL = "llama-3.3-70b-versatile"

# Words that carry no search signal — stripped before keyword scoring so a
# verbose description ("I'm looking for a ...") still scores on the real terms.
_STOPWORDS = {
    "a", "an", "the", "for", "with", "and", "or", "to", "of", "in", "on",
    "under", "size", "i", "im", "i'm", "looking", "want", "need", "find",
    "my", "mostly", "wear", "what", "is", "out", "there", "how", "would",
    "it", "this", "that", "some", "thats", "really", "very",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _chat(messages: list[dict], temperature: float) -> str:
    """Single Groq chat completion → trimmed string. Raises on API failure."""
    client = _get_groq_client()
    resp = client.chat.completions.create(
        model=_MODEL,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    listings = load_listings()

    # 1. Tokenize the description into meaningful lowercase keywords.
    tokens = [
        t for t in re.findall(r"[a-z0-9]+", description.lower())
        if t and t not in _STOPWORDS
    ]

    size_q = size.strip().lower() if size else None

    scored: list[tuple[int, float, dict]] = []
    for item in listings:
        # 2a. Price filter (inclusive).
        if max_price is not None and item["price"] > max_price:
            continue
        # 2b. Size filter — case-insensitive substring so "M" matches "S/M".
        if size_q is not None and size_q not in item["size"].lower():
            continue

        # 3. Score by keyword overlap. Title and style_tags are weighted higher
        #    than description/category/colors since they're the strongest signal.
        strong = " ".join([item["title"], " ".join(item["style_tags"])]).lower()
        weak = " ".join(
            [item["description"], item["category"], " ".join(item["colors"])]
        ).lower()

        score = 0
        for tok in tokens:
            if tok in strong:
                score += 2
            elif tok in weak:
                score += 1

        # 4. Drop anything with no keyword overlap.
        if score > 0:
            scored.append((score, item["price"], item))

    # 5. Sort by score (desc), then price (asc) as a stable tiebreaker.
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [item for _, _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handled gracefully.

    Returns:
        A non-empty string with outfit suggestions. If the wardrobe is empty,
        offers general styling advice for the item instead of crashing.
    """
    item_desc = (
        f"{new_item.get('title', 'this item')} "
        f"(category: {new_item.get('category', 'unknown')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # Empty-wardrobe branch: general styling advice, no named pieces.
        prompt = (
            f"A shopper is considering this secondhand piece: {item_desc}.\n"
            "They have NOT entered any wardrobe items yet. In 2-3 sentences, give "
            "general styling advice: what kinds of pieces, colors, and footwear "
            "pair well with it, and what overall vibe it suits. Do not invent "
            "specific items they own. Be concrete and friendly."
        )
    else:
        # Populated-wardrobe branch: name real pieces from their closet.
        closet = "\n".join(
            f"- {it['name']} ({it['category']}; "
            f"{', '.join(it.get('colors', []))}; "
            f"{', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            f"A shopper is considering this secondhand piece: {item_desc}.\n\n"
            f"Here is their existing wardrobe:\n{closet}\n\n"
            "Suggest 1-2 complete outfits that pair the new piece with specific "
            "items from their wardrobe (refer to the owned pieces by name). Keep "
            "it to 2-4 sentences, describe the vibe, and add one concrete styling "
            "tip (e.g. how to tuck, roll, or layer)."
        )

    try:
        return _chat(
            [
                {
                    "role": "system",
                    "content": "You are FitFindr, a warm, knowledgeable personal "
                    "stylist for secondhand fashion. You give specific, wearable advice.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
    except Exception as e:  # network / API / key error — never raise to caller
        colors = ", ".join(new_item.get("colors", [])) or "neutral"
        return (
            f"(Styling assistant unavailable — {type(e).__name__}.) "
            f"{new_item.get('title', 'This piece')} works well with simple "
            f"pieces in {colors} tones; pair it with well-fitting denim and clean "
            f"shoes to let it stand out."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2-4 sentence string usable as an Instagram/TikTok caption. If outfit is
        empty or missing, returns a descriptive error message string — does NOT
        raise an exception.
    """
    # 1. Guard against an empty / whitespace-only outfit.
    if not outfit or not outfit.strip():
        return "Can't write a fit card without an outfit suggestion — try a different search."

    title = new_item.get("title", "this thrifted find")
    price = new_item.get("price", "?")
    platform = new_item.get("platform", "secondhand")

    prompt = (
        f"Write a short, shareable Instagram/TikTok caption for an outfit built "
        f"around a thrifted piece.\n\n"
        f"Item: {title}\nPrice: ${price}\nPlatform: {platform}\n"
        f"Outfit / vibe: {outfit}\n\n"
        "Rules:\n"
        "- 2-4 sentences, casual and authentic (a real OOTD post, NOT a product description).\n"
        f"- Mention the item name, the ${price} price, and {platform} naturally, once each.\n"
        "- Capture the outfit vibe in specific terms. Emoji are welcome but optional.\n"
        "Return only the caption text."
    )

    try:
        return _chat(
            [
                {
                    "role": "system",
                    "content": "You write punchy, authentic secondhand-fashion "
                    "captions that sound like a real person posting their outfit.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,  # high temp so repeated calls vary
        )
    except Exception as e:  # never raise — return a usable fallback caption
        return (
            f"(Caption generator unavailable — {type(e).__name__}.) "
            f"scored this {title} on {platform} for ${price} and it's already a favorite ✨"
        )
