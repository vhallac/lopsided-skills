# 009 — language extractor dispatch for the contracts substrate

Status: accepted
Date: 2026-10-20
Refs: issue #20; PR #21

## Decision

`generate.py` is language-agnostic: files are claimed by extension into
extractors, each extractor yields the same interface/call-site structures,
and mixed-language `source_trees` merge into one registry. `.py` is parsed
with stdlib `ast` (always available); `.ts`/`.tsx` are parsed with
tree-sitter (optional dependency, declared in
`skills/emergent-contract-coding/scripts/requirements.txt`);
extensions without an extractor are skipped. The TS extractor is imported
lazily inside the collect step to avoid a circular import.

## Rationale

Adding a language must not fork the substrate into per-language tools or
duplicate the generate/check/resolve/log pipeline. A single dispatch point
(`_extractor_for` by suffix) keeps new languages additive: implement an
`Extractor` returning the shared structures, register it in the dispatch.
The optional tree-sitter dependency keeps the substrate runnable in bare
environments — TS tests skip (never fail) without it, mirroring the
Python-only behavior everywhere else.

## Scope note

Top-level TS declarations being wrapped in `export_statement` is an
implementation detail of `ts_extract.py` (defs lookup unwraps it), not part
of this contract; other grammars will have their own wrapper quirks.
