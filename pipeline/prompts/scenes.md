<!--
Prompt template for the `scenes` stage (PLAN.md sections 0 and 2). It holds no article
content: pipeline/scenes.py fills each {{name}} from config.yaml, the front matter and
the sentences file. Blocks between an "if promotional" or "if not promotional" marker
and the next "end" marker are kept only when the front matter matches.
The example at the end is made up. This comment is removed before sending.
-->
You write the scene plan for a short explainer video. Use ONLY the article below. It
is given as numbered entries, one per line:

    [number] (section) kind: text

`kind` is `text`, `list item N.` (item N of a numbered list), `quote`, `table header`
or `table row`. Table cells are separated by " | ", in the order of the table header
just above the rows.

Return JSON only, matching the response schema: {"scenes": [...]}.

## Hard rules (a script checks every one; any failure sends your answer back)

1. **Facts come only from what you cite.** Every voiceover line, every on-screen text
   and every visual item has its own `source_ids`: the numbers of the entries its
   facts come from. Cite every entry a fact comes from, and only those. No outside
   knowledge, no conclusions the article does not state, no "that means".
2. **Numbers exactly as written.** Write every number as digits, exactly as the cited
   entries write it (keep "$", "GBP", "%", decimals and commas). Never round, convert,
   add, subtract or compute. Every number you write must appear in the cited entries
   of that same line or item. Number words count as numbers: "one", "two", "nine"
   are checked too, so write "each" instead of "every one" and avoid "one of" unless
   the cited entry says it.
3. **Ranks are not counts.** Words like "first", "1st", "#1", "No. 1", "ranked 2" are
   ranks. A rank must match a rank in the cited entries: a rank word, a "(1)"-style
   marker, a numbered list item, or the value in a rank column of a table row. A
   count (for example "1 minimum" or "9 companies") never supports a rank.
4. **Visual items pair a label with a value.** For `bar_chart`, `big_number` and
   `price_cards`, each item's `label` and `value` must both appear in ONE cited entry
   (for a table row: the label in one cell and the value in that same row). Copy
   them from that entry; `value` is a number or price as written there.
5. **On-screen text without a citation has no numbers.** Headlines that make no
   claim get `source_ids: []` and must not contain any digit or number word.
6. **Quotes are word for word.** An on-screen text with role `quote` must be copied
   exactly from its cited entry.
7. **Scene ids** are 1, 2, 3 ... in order.
8. **Who claims what.** `claim_owner` is `publisher` for claims the publisher makes
   (rankings, scores, its own data or advice), `company:<exact company name>` for a
   result a company reports about itself, and `none` only for a scene that makes no
   claim at all (then every line and text in it has `source_ids: []` and no numbers).
   In a `publisher` or `company:` scene, every voiceover line must cite at least one
   entry.
<!-- if promotional -->
9. **This article is promotional: {{publisher}} publishes it and ranks or promotes
   itself.**
   - Scene 1 is a disclosure: `visual.type` "card" with `variant` "disclosure",
     `claim_owner` "publisher". Its voiceover names {{publisher}}, says it publishes
     the piece (use one of: {{publish_words}}) and says it ranks itself (use one of:
     {{rank_words}}). Cite the entries that say so. In scene 1 the disclosure itself
     is the attribution; do not add "according to" there.
   - Every other `publisher` scene has one of these phrases in its voiceover, exactly
     as written: {{attribution_phrases}}.
   - A `company:<name>` scene names that company in its voiceover as the source, and
     cites at least one entry that names the company.
<!-- end -->
<!-- if not promotional -->
9. **Attribution.** This article is not marked promotional. Still give each scene the
   right `claim_owner`; a `company:<name>` scene names that company in its voiceover
   and cites at least one entry that names it.
<!-- end -->
10. **Length.** All voiceover lines together have {{word_lo}}-{{word_hi}} words
    (the video runs {{seconds}} seconds at {{wpm}} words per minute). Count carefully.
11. **Shape.** `visual.type` is one of: {{visual_types}}.
    - `card` needs `variant`: "title", "disclosure" or "outro", and no items.
    - `big_number`: 1-3 items. `bar_chart`: 2-10 items (use the article's tables).
      `price_cards`: 1-4 items.
    - `bullets`: at least 2 on-screen texts with role "bullet", no items.
    - `quote`: exactly 1 on-screen text with role "quote", no items.
    - `icon` (optional) is a Lucide icon name in kebab-case, for example "info",
      "bar-chart-3", "badge-dollar-sign", "list-checks", "quote", "search". Icons are
      generic symbols, never a logo.
    - On-screen roles: "headline" (up to 8 words), "sub", "bullet", "quote". Do not
      number list items; the renderer does that.

## Avoid (a person reviews these; they do not fail the check)

- Inference words: {{inference_words}}.
- Judging words the cited entries do not use about that thing: {{judging_words}}.
- Drawing on fewer than {{min_sections}} sections of the article.

## A good video

{{scene_hint}} scenes. Cover the whole article, not only the opening paragraphs: the
main points a reader needs to choose or understand the topic, with at least one
scene built from a table (`bar_chart` or `price_cards`). Open with the disclosure if
the article is promotional, then the useful points, then a short close that says
where the information comes from (it may be a `card` of variant "outro" with
`claim_owner` "publisher" and an attribution phrase, citing the entry it rests on).
Plain spoken English, short sentences, one claim per voiceover line.

## Example of the shape (made-up article, not this one)

A made-up article by "Lumen Bakes" ranks bakeries and puts itself first. Two scenes
from such a plan:

```json
{"scenes": [
  {"id": 1, "claim_owner": "publisher",
   "visual": {"type": "card", "variant": "disclosure", "icon": "info"},
   "on_screen": [{"role": "headline", "text": "Who wrote this guide", "source_ids": []}],
   "voiceover": [{"text": "Lumen Bakes publishes this bakery guide and ranks itself first.",
                  "source_ids": [3, 4]}]},
  {"id": 2, "claim_owner": "publisher",
   "visual": {"type": "bar_chart", "icon": "bar-chart-3",
              "items": [{"label": "Lumen Bakes", "value": "47", "source_ids": [12]},
                        {"label": "Crumb and Co", "value": "41", "source_ids": [13]}]},
   "on_screen": [{"role": "headline", "text": "Scores out of 50", "source_ids": [10]}],
   "voiceover": [{"text": "According to Lumen Bakes, each bakery was scored out of 50.",
                  "source_ids": [10]}]}
]}
```

## The article ({{sentence_count}} entries)

{{sentences}}
