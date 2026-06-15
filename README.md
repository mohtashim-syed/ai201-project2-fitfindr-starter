# FitFindr 🛍️

FitFindr is a single-turn styling agent for secondhand shopping. You describe what you want
("vintage graphic tee under $30, size M"), and it finds a matching listing in a mock marketplace,
suggests an outfit using pieces you already own, and writes a shareable social-media "fit card"
caption for the find — all driven by a conditional planning loop, not a fixed script.

See [`planning.md`](planning.md) for the full design spec (tool contracts, planning-loop logic,
architecture diagram, and a step-by-step interaction walkthrough).

---

## Setup

```bash
pip install -r requirements.txt
```

Add your Groq API key to a `.env` file in the project root (free key at
[console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

Run the app:

```bash
python app.py        # then open the localhost URL shown in the terminal
```

Run the tests:

```bash
pytest tests/
```

> **Environment note:** this project was built on Python 3.9. The starter type hints use the
> `str | None` (PEP 604) syntax, so each module starts with `from __future__ import annotations`
> to keep that valid on 3.9. `gradio==4.44.1` also requires `huggingface_hub<0.26` (newer versions
> removed `HfFolder`), which is pinned in `requirements.txt`.

---

## Tool Inventory

| Tool | Inputs | Output | Purpose |
|------|--------|--------|---------|
| **`search_listings`** | `description: str`, `size: str \| None`, `max_price: float \| None` | `list[dict]` of listing dicts (`id, title, description, category, style_tags, size, condition, price, colors, brand, platform`), ranked by relevance; `[]` if none match | Filter the 40-item mock dataset by keywords + optional size/price and rank by keyword overlap |
| **`suggest_outfit`** | `new_item: dict` (a listing), `wardrobe: dict` (`{"items": [...]}`) | `str` of styling advice (1–2 outfits) | Pair the found item with the user's owned pieces via the LLM; falls back to general advice if the wardrobe is empty |
| **`create_fit_card`** | `outfit: str`, `new_item: dict` | `str` — a 2–4 sentence caption | Turn the outfit into a casual, shareable OOTD caption (high temperature, so it varies) |

Both `suggest_outfit` and `create_fit_card` call Groq's `llama-3.3-70b-versatile`.

### `search_listings` ranking

The description is lowercased and tokenized (stopwords like "looking", "for", "a" are dropped).
Each surviving listing — after the `max_price` and case-insensitive substring `size` filters — is
scored by keyword overlap: **+2** for a token appearing in the title or `style_tags` (strong signal),
**+1** for the description, category, or colors. Listings scoring 0 are dropped; results are sorted by
score (then price ascending as a tiebreaker).

---

## How the Planning Loop Works (the decisions it makes)

`run_agent(query, wardrobe)` in [`agent.py`](agent.py) runs a fixed three-tool sequence guarded by a
conditional early-exit. It is not "always call all three tools" — the second and third tools only run
if the first succeeds.

1. **Parse the query** (`_parse_query`, regex — no LLM). Extracts `max_price` (`under $30` → `30.0`),
   `size` (`size M` → `"M"`, `size 8` → `"8"`), and a cleaned `description` (price/size phrases stripped).
2. **`search_listings(...)`** with those parameters.
   - **Decision point:** if the result list is **empty**, set `session["error"]` to a specific,
     actionable message and **return immediately**. The styling tools are never called with empty input.
   - Otherwise, set `session["selected_item"] = results[0]` (the top-ranked listing) and continue.
3. **`suggest_outfit(selected_item, wardrobe)`** → `session["outfit_suggestion"]`.
4. **`create_fit_card(outfit_suggestion, selected_item)`** → `session["fit_card"]`.
5. **Return** the completed session.

The agent's behavior therefore differs by input: an impossible query (`"designer ballgown size XXS
under $5"`) exits after one tool call with an error; a matching query runs all three and populates
every panel.

---

## State Management

A single `session` dict (built by `_new_session`) is the source of truth for one interaction. Each
tool writes its output to a named field; the next tool reads from that field — nothing is re-derived
or re-prompted mid-run.

```
query → parsed{description,size,max_price} → search_results → selected_item
      → outfit_suggestion → fit_card        (or error, set by the guard and checked first)
```

The exact dict at `search_results[0]` is stored in `selected_item` and passed **by reference** into
both LLM tools — verified in testing (`session["selected_item"] is session["search_results"][0]` →
`True`). So the listing the user sees is literally the one that was styled and captioned. `app.py`
reads only the final session and maps its fields to the three UI panels (checking `error` first).

---

## Error Handling (with examples from testing)

| Tool | Failure mode | What the agent does |
|------|--------------|---------------------|
| `search_listings` | No listings match | Returns `[]` (no exception). The loop sets a specific error and stops. |
| `suggest_outfit` | Wardrobe is empty | Switches to a general-advice prompt; returns useful styling text. |
| `create_fit_card` | Outfit string empty/whitespace | Returns a descriptive error string instead of calling the LLM. |
| both LLM tools | Groq API/network error | Caught; returns a deterministic fallback string (never raises). |

**Concrete triggered examples (Milestone 5):**

```text
# 1. No results
$ python -c "from tools import search_listings; print(search_listings('designer ballgown', size='XXS', max_price=5))"
[]

# ...and through the full agent, the user gets an actionable message:
No listings matched 'designer ballgown' (size=XXS, under $5).
Try removing the size filter, raising your budget, or using broader keywords.

# 2. Empty wardrobe → general advice (no crash, no empty string)
$ python -c "from tools import search_listings, suggest_outfit; from utils.data_loader import get_empty_wardrobe; print(suggest_outfit(search_listings('vintage graphic tee', None, 50)[0], get_empty_wardrobe()))"
This adorable Y2K baby tee is perfect for creating a playful, nostalgic look. You can pair it
with high-waisted jeans or a flowy skirt in neutral colors ... (full advice string)

# 3. Empty outfit → descriptive error string (no exception)
$ python -c "from tools import search_listings, create_fit_card; print(create_fit_card('', search_listings('vintage graphic tee', None, 50)[0]))"
Can't write a fit card without an outfit suggestion — try a different search.
```

All three are covered by automated tests in [`tests/test_tools.py`](tests/test_tools.py)
(`pytest tests/` → 9 passed).

---

## AI Usage

I used **Claude (via Claude Code)** throughout, feeding it specific sections of `planning.md` rather
than vague prompts. Two representative instances:

1. **Implementing `search_listings`.** *Input:* the Tool 1 spec block from `planning.md` (inputs,
   return schema, "returns `[]` not an exception" failure mode) plus the `load_listings()` docstring.
   *Produced:* a function that filtered by price/size and scored by keyword overlap. *What I
   changed/overrode:* the first draft used a flat keyword count, which let any item tagged `vintage`
   (29 of 40 listings) rank as high as an actual graphic tee. I changed the scoring to weight title +
   `style_tags` matches at **+2** vs. **+1** elsewhere, and added a stopword filter so verbose queries
   ("I'm looking for a…") still score on the real keywords. I verified against the three pytest cases
   and confirmed an actual tee ranks first for "vintage graphic tee".

2. **Implementing the planning loop (`run_agent`).** *Input:* the Planning Loop, State Management, and
   Architecture (diagram) sections of `planning.md`, plus the `run_agent` TODO. *Produced:* the
   parse → search → (guard) → select → suggest → fit-card sequence writing to the session dict. *What
   I checked/overrode:* I confirmed it branches on the empty-results case and returns early instead of
   calling the styling tools unconditionally, and that `selected_item` is exactly `search_results[0]`
   (passed by reference, not copied). I also tightened the regex query parser so "size M" and "size 8"
   are extracted as the `size` filter rather than leaking into the keyword description.

---

## Spec Reflection

Writing the tool contracts and the conditional planning-loop logic in `planning.md` *before* coding
made the implementation almost mechanical — the early-exit branch and the by-reference state hand-off
were already decided, so the generated code had a precise target to hit. The one place reality pushed
back on the spec was `search_listings` relevance: the dataset's heavy use of the `vintage` tag meant a
naive overlap score didn't match my walkthrough's expectation, so I refined the scoring (weighted
fields + stopwords) and updated the spec to match. The failure-mode rows in the spec table translated
directly into both the guards in the code and the tests — testing each tool in isolation first meant
wiring the loop together surfaced zero surprises.

---

## Project Structure

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # wardrobe format + example/empty wardrobes
├── utils/data_loader.py       # load_listings / get_example_wardrobe / get_empty_wardrobe
├── tools.py                   # the 3 tools
├── agent.py                   # run_agent() planning loop + query parser + session state
├── app.py                     # Gradio UI + handle_query()
├── tests/test_tools.py        # pytest: one+ test per failure mode
├── planning.md                # design spec (read this first)
└── requirements.txt
```
