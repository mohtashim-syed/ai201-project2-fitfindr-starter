# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## What FitFindr Does (overview)

FitFindr is a single-turn styling agent for secondhand shopping. Given one natural-language
request, it (1) **searches** a mock marketplace of 40 listings for items matching the user's
description, size, and price ceiling; (2) **suggests an outfit** that pairs the best match with
pieces the user already owns; and (3) **writes a shareable "fit card"** caption for the find.
The planning loop runs these three tools in a fixed order, but it is *conditional*: if the search
returns nothing, the agent stops, reports what failed, and never calls the styling tools with empty
input. Each tool also degrades gracefully on its own failure mode (empty wardrobe, missing outfit).

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the 40-item mock listings dataset (loaded via `load_listings()`) and returns the listings
that match a keyword description, with optional size and price filters, ranked by how well they match.

**Input parameters:**
- `description` (str): Free-text keywords describing the wanted item, e.g. `"vintage graphic tee"`. Tokenized into lowercase words and matched against each listing's `title`, `description`, `style_tags`, `category`, and `colors`.
- `size` (str | None): A size string to filter by, e.g. `"M"`. Matching is case-insensitive **substring** matching so `"M"` matches `"S/M"` and `"M/L"`. `None` skips size filtering.
- `max_price` (float | None): Inclusive price ceiling, e.g. `30.0`. Listings with `price > max_price` are dropped. `None` skips price filtering.

**What it returns:**
A `list[dict]` of matching listing dicts, sorted by relevance score (highest first). Each dict has the
full listing schema: `id`, `title`, `description`, `category`, `style_tags` (list), `size`,
`condition`, `price` (float), `colors` (list), `brand` (str | None), `platform`. Listings whose
keyword-overlap score is 0 are excluded. Returns `[]` (never raises) when nothing matches.

**What happens if it fails or returns nothing:**
Returns an empty list `[]`. The planning loop detects the empty list, sets `session["error"]` to a
specific, actionable message (what was searched + what to relax), and returns early **without** calling
`suggest_outfit` or `create_fit_card`.

---

### Tool 2: suggest_outfit

**What it does:**
Takes the selected listing and the user's wardrobe and asks the LLM (Groq `llama-3.3-70b-versatile`)
to propose 1–2 complete, specific outfits that combine the new item with named pieces the user owns.

**Input parameters:**
- `new_item` (dict): A listing dict (the top search result) — the piece being styled. The function uses its `title`, `category`, `colors`, `style_tags`, and `condition` in the prompt.
- `wardrobe` (dict): A wardrobe dict shaped `{"items": [ {id, name, category, colors, style_tags, notes}, ... ]}`. The `items` list may be empty.

**What it returns:**
A non-empty `str` of styling advice. With a populated wardrobe it names specific owned pieces
("pair with your wide-leg khaki trousers and chunky white sneakers"). With an empty wardrobe it
returns general styling guidance (what categories/colors/vibe pair well) instead of naming items.

**What happens if it fails or returns nothing:**
If `wardrobe["items"]` is empty, the tool switches to a "general advice" prompt rather than crashing.
If the LLM call raises (network/key error), it returns a plain fallback string describing the item and
generic pairing advice — it never raises to the caller.

---

### Tool 3: create_fit_card

**What it does:**
Generates a short, casual, shareable social-media caption ("fit card") for the thrifted find, based on
the outfit suggestion and the item details. Calls the LLM at a higher temperature so repeated calls vary.

**Input parameters:**
- `outfit` (str): The outfit-suggestion string returned by `suggest_outfit()`. Drives the vibe of the caption.
- `new_item` (dict): The listing dict, so the caption can mention the item `title`, `price`, and `platform` naturally (once each).

**What it returns:**
A 2–4 sentence `str` usable as an Instagram/TikTok caption — casual, authentic, vibe-forward, mentioning
the item name, price, and platform once each. Varies between calls (temperature ≈ 0.9).

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, it returns a descriptive error string
(`"Can't write a fit card without an outfit suggestion."`) rather than calling the LLM or raising.
If the LLM call raises, it returns a simple fallback caption built from the item fields.

---

### Additional Tools (if any)

None — the three required tools cover the full interaction.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed sequence with conditional early-exit guards. State lives in one `session` dict.

1. **Initialize**: `session = _new_session(query, wardrobe)`.
2. **Parse the query** (string/regex parsing, no LLM): extract
   - `max_price` — regex for `under $30`, `$30`, `30 dollars` → first number found, else `None`.
   - `size` — regex for `size M`, `size 8`, or a standalone size token (`XS|S|M|L|XL|US \d+`), else `None`.
   - `description` — the query with the price/size phrases stripped out, used as keywords.
   Store all three in `session["parsed"]`.
3. **search_listings(description, size, max_price)** → `session["search_results"]`.
   - **Branch A — `results == []`:** set `session["error"]` to a specific message
     (`"No listings matched '<description>' (size=<size>, under $<price>). Try removing the size filter, raising your budget, or using broader keywords."`) and **`return session` immediately**. Do not proceed.
   - **Branch B — `results` non-empty:** set `session["selected_item"] = results[0]` (top-ranked) and continue.
4. **suggest_outfit(selected_item, wardrobe)** → `session["outfit_suggestion"]`. Always returns a usable
   string (handles empty wardrobe internally), so no early exit here.
5. **create_fit_card(outfit_suggestion, selected_item)** → `session["fit_card"]`. If `outfit_suggestion`
   came back empty for any reason, `create_fit_card` returns an error string instead of crashing.
6. **Return** the completed `session`.

The loop "knows it's done" when it reaches step 6 (all three fields populated) or when an early-exit
guard fires (step 3, Branch A). Behavior differs by input: an impossible query exits after one tool call;
a matching query runs all three.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created by `_new_session()` in `agent.py`) is the single source of truth for a
run. Each tool's output is written to a named field, and the next tool reads from that field — nothing is
re-derived or re-prompted from the user mid-run.

| Field | Written by | Read by |
|-------|-----------|---------|
| `query` | caller | step 2 (parsing) |
| `parsed` (`{description, size, max_price}`) | step 2 | `search_listings` |
| `search_results` (list[dict]) | `search_listings` | step 3 guard / selection |
| `selected_item` (dict) | step 4 | `suggest_outfit`, `create_fit_card` |
| `wardrobe` (dict) | caller | `suggest_outfit` |
| `outfit_suggestion` (str) | `suggest_outfit` | `create_fit_card` |
| `fit_card` (str) | `create_fit_card` | UI |
| `error` (str \| None) | any guard | UI (checked first) |

The exact dict in `search_results[0]` is what gets stored in `selected_item` and passed by reference into
both LLM tools — there is no copying or re-fetching, so what the user sees as the "top listing" is
literally what was styled. `app.py` reads only the final `session` and maps fields to the three panels.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Returns `[]`. Loop sets `session["error"] = "No listings matched '<description>' (size=<size>, under $<price>). Try removing the size filter, raising your budget, or using broader keywords."`, leaves `outfit_suggestion`/`fit_card` as `None`, and returns early. UI shows this message in the listing panel and leaves the other two blank. |
| suggest_outfit | Wardrobe is empty (`items == []`) | Does not crash. Switches to a general-styling prompt and returns advice like "This faded band tee leans 90s grunge — pair it with baggy jeans and chunky boots; start a wardrobe to get picks using your own pieces." |
| create_fit_card | Outfit input is missing or incomplete | Guards `if not outfit.strip()`: returns the string `"Can't write a fit card without an outfit suggestion — try a different search."` instead of calling the LLM or raising. |

(Additional defensive guard, not required but implemented: both LLM tools catch network/API exceptions and
return a deterministic fallback string so a transient Groq error never bubbles up as an unhandled exception.)

---

## Architecture

```
                      User query  +  wardrobe choice
                              │
                              ▼
        ┌──────────────────────────────────────────────────────────────┐
        │                      PLANNING LOOP  (run_agent)                │
        │                                                                │
        │  parse query ──► session["parsed"] = {description,size,price}  │
        │      │                                                         │
        │      ▼                                                         │
        │  search_listings(description, size, max_price)                 │
        │      │                                                         │
        │      ├── results == []  ──►  session["error"] = "No listings…" │
        │      │                        outfit/fit_card stay None        │
        │      │                        └──────────────► RETURN (early) ─┼──► UI
        │      │                                                         │
        │      │ results = [item, …]                                     │
        │      ▼                                                         │
        │  session["selected_item"] = results[0]                         │
        │      │                                                         │
        │      ▼                                                         │
        │  suggest_outfit(selected_item, wardrobe)                       │
        │      │   (empty wardrobe → general advice, never crashes)      │
        │      ▼                                                         │
        │  session["outfit_suggestion"] = "..."                          │
        │      │                                                         │
        │      ▼                                                         │
        │  create_fit_card(outfit_suggestion, selected_item)             │
        │      │   (empty outfit → error string, never crashes)          │
        │      ▼                                                         │
        │  session["fit_card"] = "..."                                   │
        │      │                                                         │
        └──────┼─────────────────────────────────────────────────────────┘
               ▼
          RETURN session  ──►  app.py maps fields ──►  [listing | outfit | fit card] panels

  SESSION STATE (single source of truth, passed by reference between tools):
    query → parsed → search_results → selected_item → outfit_suggestion → fit_card | error
```

---

## AI Tool Plan

**Tool of choice:** Claude (via Claude Code) for all implementation, because I can hand it whole spec
sections from this file and have it edit the actual `tools.py` / `agent.py` stubs in place.

**Milestone 3 — Individual tool implementations:**
- **search_listings:** Give Claude the *Tool 1* block (inputs, return schema, failure mode) + the
  `load_listings()` docstring. Expect: a function that loads listings, applies the `max_price` then
  case-insensitive substring `size` filter, scores remaining listings by lowercase keyword overlap across
  title/description/style_tags/category/colors, drops score-0 items, and returns sorted dicts.
  **Verify before trusting:** confirm it filters by all three params and returns `[]` (not `None`/exception)
  on no match; run the three pytest cases (`returns_results`, `empty_results`, `price_filter`).
- **suggest_outfit:** Give Claude the *Tool 2* block + wardrobe schema. Expect: empty-wardrobe branch
  (general advice) vs populated branch (named pieces), a single Groq `llama-3.3-70b-versatile` call,
  try/except fallback. **Verify:** call once with `get_example_wardrobe()` (output names real pieces) and
  once with `get_empty_wardrobe()` (no crash, general advice).
- **create_fit_card:** Give Claude the *Tool 3* block. Expect: empty-outfit guard returning an error
  string, higher temperature (~0.9), item name/price/platform mentioned once. **Verify:** run 3× on the
  same input and confirm captions differ; call with `outfit=""` and confirm an error string, not an exception.

**Milestone 4 — Planning loop and state management:**
- Give Claude the *Planning Loop*, *State Management*, and *Architecture* (diagram) sections plus the
  `run_agent` TODO. Expect: query parsing → `search_listings` → empty-result early return setting
  `session["error"]` → select `results[0]` → `suggest_outfit` → `create_fit_card`, all writing to the
  session dict. **Verify before trusting:** confirm it branches on the empty result (does *not* call the
  styling tools unconditionally), that `selected_item` is exactly `search_results[0]`, and run both CLI
  cases in `agent.py` (happy path populates all fields; no-results path sets `error` and leaves
  `fit_card = None`).

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse + Search.**
The loop parses the query → `description="vintage graphic tee"`, `size=None`, `max_price=30.0`, stored in
`session["parsed"]`. It calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. This
returns the graphic-tee matches under $30 ranked by keyword overlap — e.g.
`[lst_033 "Vintage Band Tee — Faded Grey" $19, lst_006 "Graphic Tee — 2003 Tour Bootleg Style" $24,
lst_002 "Y2K Baby Tee — Butterfly Print" $18]`. Non-empty → no early exit.
`session["selected_item"] = results[0]` (the Vintage Band Tee).

**Step 2 — Suggest outfit.**
The loop calls `suggest_outfit(selected_item=<Vintage Band Tee>, wardrobe=get_example_wardrobe())`. The
LLM sees the tee plus the user's owned pieces and returns something like: "Pair this faded band tee with
your baggy straight-leg jeans and chunky white sneakers for an effortless 90s grunge look — layer the
vintage black denim jacket on top and roll the sleeves once." Stored in `session["outfit_suggestion"]`.

**Step 3 — Create fit card.**
The loop calls `create_fit_card(outfit=<the suggestion>, new_item=<Vintage Band Tee>)`. The LLM returns a
caption like: "found this faded vintage band tee on depop for $19 and it's already my most-worn 🖤 styled
it with baggy jeans + chunky sneakers, denim jacket on top. grunge szn." Stored in `session["fit_card"]`.

**Final output to user:**
The Gradio UI shows three panels: **Top listing** ("Vintage Band Tee — Faded Grey · $19 · fair · depop"),
**Outfit idea** (the Step-2 styling text), and **Your fit card** (the Step-3 caption). `session["error"]`
is `None`.

**Error path variant:** For "designer ballgown size XXS under $5", Step 1's `search_listings` returns `[]`.
The loop sets `session["error"] = "No listings matched 'designer ballgown' (size=XXS, under $5). Try
removing the size filter, raising your budget, or using broader keywords."` and returns early — Steps 2–3
never run, and the outfit/fit-card panels stay blank.
