---
name: zettelkasten-notetaking
description: Maintain a zettelkasten-style running-notes store for a project. Use when the project contains a .notes/zettel-index.md signature file, or when the user asks to write, search, link, validate, or maintain zettel notes. Covers card writing with index-in-context placement, typed link discovery, random walks, structural validation, and periodic network maintenance.
---

# Zettelkasten Notetaking

A two-file note system designed for LLM maintainers: small, greppable, and always placeable without reading the whole store.

## Files

- `.notes/zettel.md` — the cards. Hline-separated, append-and-place only.
- `.notes/zettel-index.md` — the index. One line per card: `ID — Title`, optionally followed by a status annotation: `ID — Title [verified]` or `ID — Title [superseded → 4.1]`. Unsorted by design; short enough to load fully into context on every operation.
- `.notes/.git/` — a nested, local-only Git repository. It records note history and MUST have no configured remote; this skill never pushes it.
- `.notes/.store-state` — a tamper ticket written and verified by `store.py` on every commit, plus a pre-commit hook in `.notes/.git/hooks/` that rejects commits whose content does not match it. Never read, edit, delete, or recreate this file; never bypass the hook with `--no-verify`.
- `.notes/READ-ME-FIRST-use-skill-zettelkasten-notetaking.md` — a non-hidden guard/tripwire file. Its imperative name appears in every directory listing, and its content instructs a reader to load this skill. `store.py init` creates it; the pre-commit hook rejects any commit that modifies or deletes it; `store.py` recreates it automatically on every mutating command if it is ever deleted or altered. Treat it as immutable — never edit or delete it yourself.

The presence of `.notes/zettel-index.md` in the project activates this skill.

## Paths

`<skill-directory>` means the directory containing this SKILL.md, wherever your agent installed it (user-level, project-level, or per-agent — locations vary). Never guess a fixed absolute path for it; always use the placeholder. The notes store itself lives under `<project-root>/.notes/`, independent of the skill's location.

## Store commands and local history

The LLM decides a card's placement, title, body, and meaningful relationships. It does not edit
note files directly. `store.py` owns every mechanical mutation: placement, index updates,
validation, and local Git history.

**Using `store.py` is non-negotiable.** In one session an agent, unable to locate
`store.py`, fell back to hand-editing the cards and ran an ad-hoc structural check that
reported "all clean" — while leaving five links without reciprocal backlinks, silently
invalidating the store. The fallback validator could not be trusted to own the invariant;
only `store.py` can. If `store.py` cannot be found or run, HALT the note-taking and report
the problem to the user instead of trying to wing it. Never hand-edit `.notes/` files and
never substitute your own validator for `store.py validate`.

Initialize the nested local-only repository once before writing cards:

```sh
python3 <skill-directory>/scripts/store.py init <project-root>
```

The command refuses a configured remote, records the existing store as the initial local commit, installs the
pre-commit hook, and writes `.notes/.store-state`. Do not add a remote and never run `git push` from `.notes/`.
Every successful `add-card` or `add-link` command verifies the store state against the ticket before mutating,
validates, and commits its own change locally.

Because of the hook and the ticket, hand edits to `.notes/zettel.md` or `.notes/zettel-index.md` are detected
twice: a mutating command fails its pre-verify, and a hand-made `git commit` is rejected by the pre-commit hook
with an error pointing back to this skill.

## Operation: Repair a rejected or failed command

If a store command fails with "note files were modified outside store.py" or the pre-commit hook rejects a
commit, the note files were hand-edited. Do not fight the hook and do not recreate `.store-state` yourself:

1. Run `python3 <skill-directory>/scripts/store.py validate <project-root>`.
2. If the hand edit should be discarded, restore the committed state:
   `git -C <project-root>/.notes restore zettel.md zettel-index.md` — then redo the intended change through
   `add-card` / `add-link`.
3. If the working tree is clean but the store state is stale (the hand edit was already committed), and
   `validate` passes, run `python3 <skill-directory>/scripts/store.py re-ticket <project-root>` to record the
   validated state as a repair commit. If `validate` fails, repair only the affected cards or index entries
   as instructed by the validator, then re-run `re-ticket`.
4. Never delete or rewrite `.notes/.store-state` by hand; the only writer is `store.py`.

## Card format

```
---

# 3.1.1

## Title of the idea

Short body. One idea per card. If removing a sentence breaks the card's meaning,
the card is not atomic — split it. Ends with zero or more typed link lines:

→ 3.1 (extends): builds on the parent claim about X
← 2.2.4 (questions): challenged by the observation in 2.2.4
```

- **H1 = stable branching ID.** Zettelkasten-style, numeric all the way: `1`, `1.1`, `1.1.1`, `1.1.2`. A child appends the next dotted numeric segment to its parent's ID (sibling sequence). IDs are never reused or renumbered. Uniform numeric segments sort naturally (`sort -V`), validate with one regex, and a subtree is one literal prefix grep (`^# 1\.1\(\.\|$\)` catches all descendants of `1.1`).
- **H2 = title.** A claim, not a topic. "Random walks surface stale decisions", not "Random walks".
- **Body = short.** Feynman test: you must be able to say the idea in one sentence before writing the card. `store.py` rejects bodies over 600 characters and titles over 80; if the idea doesn't fit, split it.
- **Cold readability.** A card must make sense to someone reading it with no conversation context. No "this conversation", "step 2", "the attack above" — name the things themselves.

## Card status

Every card carries exactly one of five statuses, recorded as an annotation on its index line (the card body itself never carries status):

- `draft` (default — absent annotation means draft): captured, not yet checked.
- `verified`: claims checked against sources; a rationale is recorded in the local commit message.
- `settled`: stable and relied upon. Mutating or superseding a `settled` card requires operator confirmation first (advisory gate — see Guardrails; `store.py` will not refuse).
- `obsolete`: the idea is dropped. The card stays addressable by ID and by inbound links (children and links stay in place); it is only dropped out of discovery.
- `superseded`: the idea is replaced. The annotation names the successor: `[superseded → <id>]`.

Reading rules:

- Resolving an `obsolete` card by ID or inbound link returns the card as usual — read it with its status visible; addressability is unaffected by discovery exclusion.
- Resolving a `superseded` card surfaces the successor: follow the annotation's `→ <id>` reference and read that card. Inbound links are never rewritten — the redirect happens at resolution time, not in the link lines.

Transition statuses only through `store.py`:

```sh
python3 <skill-directory>/scripts/store.py set-status <project-root> \
  --id "<card-id>" --status "verified|settled|obsolete" --rationale "<why>"
```

`set-status` accepts `verified`, `settled`, and `obsolete` only, moving along `draft → verified → settled` or to `obsolete` from any trust level. Illegal transitions, unknown statuses, and missing rationale are rejected. The rationale is recorded in the local store commit message — the store's git history is the audit trail.

## Operation: Supersede a card

When a better idea replaces an existing one, supersede it — never delete or rewrite the old card:

1. Confirm the replacement with the operator if the old card is `settled` (advisory gate).
2. Compose the successor's claim title and body as for Write a card.
3. Run one command; it captures the successor (next available ID, content-validated like `add-card`), annotates the old card `[superseded → <successor-id>]`, validates, and commits both changes atomically:
   ```sh
   python3 <skill-directory>/scripts/store.py supersede <project-root> \
     --id "<old-card-id>" --title "<claim-title>" --body-file "<body-file>" \
     --rationale "<why the replacement>"
   ```
4. Do not rewrite inbound links of the old card — resolution-time redirect (see Card status) makes them point readers to the successor.

## Operation: Write a card

The index is in-context for every write. Do not grep for ideas; grep only for locations.

1. Ensure the local note repository exists and has no remote:
   `python3 <skill-directory>/scripts/store.py init <project-root>`.
2. Load `.notes/zettel-index.md` fully.
3. Scan titles. Shortlist the headings under which the new idea could live.
4. Read the full text of each shortlisted card in `.notes/zettel.md`.
5. If one makes sense as a parent, the new card is that parent's next child: its ID is the parent's ID plus `.N`, where N is the parent's current highest sibling leaf + 1. No gaps, no reordering — `store.py` rejects any other ID. (Sibling order = conceptual adjacency, not chronology; place later with children if needed.)
6. If none fits, create a new top-level ID.
7. Create the card only through `store.py`; it inserts after the parent's final descendant (or at end of file for top-level), appends the `ID — Title` index entry, validates, and commits:
   ```sh
   python3 <skill-directory>/scripts/store.py add-card <project-root> \
     --id "<chosen-id>" --title "<claim-title>" --body-file "<body-file>"
   ```
8. Run link search (below) before finishing.
9. Do not directly edit `.notes/zettel.md` or `.notes/zettel-index.md`.

Never move, renumber, or rewrite existing cards during a write. If an existing card contradicts the new one, link it with `contradicts` — do not silently fix it.

## Operation: Link search

Runs on every new card. Also invocable on demand for a set of IDs. Skip index entries annotated `[obsolete]` or `[superseded → ...]` when shortlisting candidates (discovery exclusion); explicit resolution of such a card follows the Card status reading rules.

Search in three passes, using the index first and reading candidate cards:

1. **Direct** — same branch, obvious relatives.
2. **Conceptual** — different branch, same underlying idea.
3. **Forced cross-domain** — pick one distant branch and ask "what would have to be true for these to connect?"
4. **Contradiction pass** — for every shortlisted candidate, explicitly ask "does anything existing contradict or question this card?" Do not stop at support/extension links; `contradicts` and `questions` are first-class kinds, not exceptional ones.

For each link found, add a typed ref and its reciprocal backlink only through `store.py`:

```sh
python3 <skill-directory>/scripts/store.py add-link <project-root> \
  --from "<source-id>" --to "<target-id>" --kind "<relationship-kind>" \
  --why "<specific rationale>"
```

The command writes `→` in the source card and `←` in the target card, then validates and commits.

- `extends` / `questions` / `supports` / `contradicts` / `analogous`
- Every link carries a `why` clause. A link without a reason is not a link.

Prefer few meaningful links over many shallow ones. Rank candidates by: meaning-depth, specificity, leverage (does this link change how either card reads?).

## Operation: Search / retrieve

**Discovery exclusion:** scan index titles but skip entries annotated `[obsolete]` or `[superseded → ...]`. The index stays complete — exclusion is behavioral, never deletion. Explicitly resolving an excluded card by ID or inbound link is still allowed and follows the Card status reading rules.

- By ID set: grep the index for IDs, then read those cards.
- By topic: scan index titles, shortlist, read full cards. Same discipline as Write steps 2–3.
- Children of a card: `grep "^# <id-prefix>\(\.\|$\)" .notes/zettel.md` — branching IDs make subtree gathering cheap.

## Operation: Validate the store

Run after any operation that changes `.notes/zettel.md` or
`.notes/zettel-index.md`, and on demand:

```sh
python3 <skill-directory>/scripts/store.py validate <project-root>
```

The checker verifies card and index syntax, numeric dotted IDs, unique IDs,
parent existence, contiguous subtrees, index/card agreement, typed-link syntax,
link targets, and reciprocal links. Orphans are warnings because a valid new
store can contain them. Do not report a mutation as complete until its store
command exits 0: successful mutations have already been validated, committed,
and checked for a clean local-only repository. If a command fails, report its
errors and repair only the affected cards or index entries.

## Operation: Random walk

Surfaces unearthed correlations. Invoke on demand or when the user asks for discovery.

1. Pick a mode: `random` (any card), `theme` (any card, then walk its links), `time` (oldest untouched card), `cross` (two cards from distant branches).
2. Sample IDs from the index (skip `obsolete` and `superseded` entries); read the cards.
3. Ask the three link questions: What does this connect to that I hadn't noticed? What does it contradict? What does it now explain?
4. If a link emerges, add it through `store.py add-link` (typed, with why, both directions).
5. If no signal: record why in the walk output and stop. Do not force a link.

## Operation: Network maintenance (periodic)

Trigger: every ~15 new cards, or on demand. This is the integration check.

1. **Integration** — do the new cards sit cleanly, or do recent additions contradict/duplicate older ones? Report; fix only by linking, never by rewriting old cards. Exclude `obsolete` and `superseded` entries from the health scan.
2. **Orphans** — cards with no inbound or outbound links. Try a link search for each; if truly orphan, flag to the user.
3. **Tertiary links** — if new card A links to B and to C, check whether B–C also merits a link. Secondary links of recent cards can also earn a direct link to the new card.
4. Report health: orphan count and rate, average link degree, and any contradiction pairs found. Interpret the structural metrics using these rough bands:
   - Orphan rate: `<5%` excellent, `5–10%` good, `10–20%` acceptable, `>20%` poor.
   - Average degree: `>3` excellent, `2–3` good, `1–2` acceptable, `<1` poor.
   Treat the bands as diagnostic signals, not targets to game with shallow links.

## Guardrails

- The index is the map; trust it before grepping bodies.
- Cards are immutable in content once written (except appended link lines). Correction = new card + `contradicts`/`extends` link.
- Never hand-edit, delete, or regenerate `.notes/.store-state`, and never commit with `--no-verify`; both exist to catch hand edits.
- Tags are deliberately deferred. Do not invent a tag system.
- Keep bodies short: at most 600 characters and 80-character titles — `store.py` rejects longer. If the idea doesn't fit, split it and link the parts. (Existing cards are immutable; the cap binds new writes only.)
- Cards move through the trust ladder only via `store.py set-status` / `supersede` (see Card status); do not delete or rewrite cards under the current append-and-place policy.
- **Advisory `settled` gate (D5):** before transitioning or superseding a `settled` card, confirm with the operator first. `store.py` does not enforce this — the check is yours.
- Do not rewrite inbound links of `superseded` cards; resolution-time redirect handles readers.
