# Review method

The review's core: what to falsify, how, how to grade what you find, and how the verdict follows. Identical for every kind of target.

## Primary review objective

The purpose of review is not merely to confirm that implementation, tests, and documentation exist. Try to determine whether the work is actually correct.

After establishing scope:

1. Extract each material behavioral claim, requirement, invariant, and contract introduced, changed, or relied upon by the work.
2. Rewrite important claims as falsifiable statements.
3. Actively try to construct a minimal counterexample.
4. Test assumptions at boundaries, empty states, failure paths, alternate control-flow paths, interleaved ordering, and asymmetric transformations.
5. Only consider a claim supported after reasonable attempts to falsify it fail. For equivalence claims, prefer discriminating inputs over empty states.

Passing tests, existing implementation, MR prose, and documentation are evidence, not authority. A test may encode the defect being reviewed.

## Claim-test presence check (first review only)

A green suite is necessary, not sufficient: passing tests without a traceable mapping do not evidence the claims they are supposed to test.

After extracting claims (step 1 of the primary review objective), and only in the **first review** of a change:

1. For each **new claim** extracted — a material claim introduced or changed by the work under review — attempt to map it to a behavioral test case or scenario via the **claim record**: the claim-block comments in the committed test files, as emitted by the `plan-work` skill during implementation (format and id syntax per its *Claim block format* spec). The mapping key is the **repo-scoped claim id + enumeration-id** (the source use-case element) → test/scenario — the first two `/`-joined components of the claim block's `claim:` field. The claim id is repo-scoped (feature-file prefix + claim id), so it resolves unambiguously even when a repository holds many claim blocks — never match on the bare, run-local claim id alone. A claim is covered only when a committed test carrying a claim block with that claim id exists in the live suite; the block's test-name component makes the claim → test link verifiable by grep alone.
2. Every new claim with no mapped test/scenario becomes a finding of the finding class **insufficient testing**, listing each unmapped `claim-id[/enumeration-id]`.
3. The absence of a test does not by itself assign an implementation defect; the finding records the coverage gap. How the gap affects the verdict is defined in [Verdict](#verdict).

**Scope of the record.** The committed claim record contains only claims that reached test code: claim blocks are emitted during implementation for claims that have a test, and a claim without a test has no committed record — it stays in the plan's planning scratchpad and is never committed. Untested claims are review-scope-only: they can be extracted, flagged, and waived during a review, but they leave no durable residue and are a fresh gap in every review that sees them.

**Reconciliation reviews never perform this check.** A reconciliation review keeps its full-suite regression pass — run the accumulated claim suite once per the change under review and report breakage on a mapped claim as a normal finding — but it does not re-derive claim coverage or raise insufficient-testing findings.

**No waiver inheritance.** A waiver granted in an earlier review never carries into a later review. If the change modifies code under a claim whose record shows a previous review's waiver (a `coverage: review-only` claim), no waiver is inherited: the operator must either re-decide the waiver for this review or a test must be added now. An unmapped claim is a fresh gap in every review that sees it.

### Locating review-only claims (later reviews)

Read the committed claim record — the claim-block comments in the committed test files (one block per claim that has a test, placed immediately above the test's declaration; see the `plan-work` skill's *Claim block format*). Locate it by searching the repository's test files for claim blocks, keyed on the repo-scoped claim id — claim blocks live in test files and may sit outside the diff's touched paths, so a touched-directory search never reaches them; never infer coverage from MR prose, commit messages, or test names. Reading the record is a read-only evidence step.

1. For each file the change under review modifies, check whether any claim block in test files that map to behavior implemented in that file covers it — the mapping condition is the file relationship (behavior implemented in the touched file), not the search root.
2. A claim whose claim block carries review-only waiver residue — an operator-appended `coverage: review-only` annotation from an earlier review's waiver — whose code is touched by this change is flagged as an **unverified-behavior change**: the finding class is **insufficient testing**, listing the touched claim's repo-scoped `claim-id[/enumeration-id]`. Reading the record is read-only — the reviewer never modifies a claim block; waiver residue is written only via the operator's post-publication waiver step.
3. Claims that never reached test code have no committed record and are review-scope-only: there is no residue to locate or inherit. No waiver is inherited from any record: the operator must re-decide the waiver for this review or a test must be added now (see the no-waiver-inheritance rule above and the waiver procedure in [Verdict](#verdict)).

When evidence conflicts, surface the conflict explicitly. Do not silently choose the implementation or existing tests as the intended behavior. Prefer explicit acceptance criteria and established external/documented contracts unless the work explicitly changes that contract.

Do not invent findings.


## Falsification procedure

Apply these checks whenever relevant.

### Limits, budgets, caps, quotas, and bounded behavior

For any claimed limit such as `N`:

- inspect `0`, `1`, `N-1`, `N`, and `N+1` behavior where meaningful;
- inspect work performed both before and after the limit is enforced;
- check whether fallback, append, retry, default, or cleanup logic can bypass the limit (see [Defaults, fallbacks, and transformations](#defaults-fallbacks-and-transformations));
- distinguish a true hard bound from a best-effort target.

A claim such as "maximum 20 entries" means no reachable path should produce 21.

### Ordering, grouping, prioritization, and recency

Do not test ordering only with naturally separated groups.

Construct an interleaved example and determine whether the guarantee is:

- global;
- per group;
- per partition;
- or merely an artifact of the current test data.

If the contract says "oldest first", "newest first", "stable", or equivalent, verify that property across group boundaries.

When defaults, fallbacks, or transformations are in play, apply [Defaults, fallbacks, and transformations](#defaults-fallbacks-and-transformations).

### Atomicity, durability, and crash-safety

For "atomic", "crash-safe", "durable", or "never partial" claims:

- state which failure the claim covers: process crash/throw, or OS crash/power loss;
- for process crashes, check every throw path between creating temporary state and publishing it, and what is left behind;
- for OS crash/power loss, check that the written file is fsynced before the rename and the containing directory after it;
- check that test seams (injected fs, clocks, etc.) are used on every path, including cleanup, so tests exercise what production runs.

If the claim or the governing decision is ambiguous about which failures it covers, raise it as a contract-wording finding (Minor), not a correctness defect.

### Tests

Treat tests as executable claims rather than proof of correctness.

For each significant test:

- determine which requirement or contract it is intended to validate;
- verify that its expected result agrees with that requirement;
- check whether its data accidentally avoids important edge cases;
- look for missing negative, boundary, interleaving, empty-state, and failure-path cases.

If a test explicitly asserts behavior that contradicts the documented or accepted contract, report the contradiction.

## Defaults, fallbacks, and transformations

### Transformations and derived representations

Whenever the change introduces or modifies normalization, filtering, cleaning, clipping, hashing, serialization, tokenization, canonicalization, or another derived representation:

1. identify every producer of that representation;
2. identify every consumer;
3. compare the transformations used at each boundary;
4. inspect runtime, rebuild, migration, import/export, query/index, write/read, and encode/decode paths separately.

Equivalent values should not accidentally pass through incompatible transformation pipelines.

**Equivalence and parity claims.** When a claim is universal over an input space ("path A and path B always produce identical output/hashes"):

1. Enumerate the claim's free input dimensions (content kinds, empty/non-empty, whitespace, multiplicity, ordering).
2. Close the claim only with (a) a structural comparison of both transformation bodies, or (b) at least one **discriminating** fixture per dimension — an input where the two paths would differ if they differ at all.
3. A fixture from the agreement region (e.g. empty input, where both sides trivially coincide) does not support the claim. "The parity test passes" is not evidence if the fixture does not exercise the compared transformation.
4. Prefer the most common production input as the discriminating fixture, not only empty/boundary cases.

### Always-on, independent, fallback, optional, and degraded behavior

When behavior is described as always-on, independent, fallback, best-effort, or optional:

- enumerate earlier returns;
- inspect empty states;
- inspect missing dependencies;
- inspect failed external calls;
- inspect degraded operation;
- inspect exception paths.

Check whether an early return, fallback, append, retry, default, or cleanup path can bypass an intended invariant.

Do not infer independence merely because components are implemented in separate functions.

### Defaults and configuration

For every changed default or configuration contract:

- identify all readers;
- identify implicit defaults at each layer;
- inspect scripts, runtime code, migrations, tests, and docs;
- determine whether behavior changed for users who do not explicitly configure the setting.

Check whether a changed default alters cost, security, retention, compatibility, resource use, or externally observable behavior.

### Trust boundaries and attack surface

For every changed input path (HTTP, CLI arg, env var, file, queue message, API payload):

- trace from entry point to dangerous sink (exec, SQL, file write, template, eval, deserialization) and identify where untrusted data crosses a trust boundary;
- check whether secrets, tokens, or credentials can appear in logs, error messages, or artifacts;
- check whether the change weakens, bypasses, or skips an authorization, authentication, or validation check — including via the early-return/fallback paths already inspected above;
- classify the trace as **validated boundary**, **unvalidated sink reachable**, or **no sink**.

Treat "unvalidated sink reachable" as a security claim subject to the same counterexample construction as any other claim.

## Code quality

After the evidence and falsification stages, run the code quality stage over the diff. Two sub-stages:

**a. Documented linter/static-analysis run.** If the reviewed project documents a linter or static-analysis stage in its agent-facing docs (AGENTS.md or equivalent), run it in the review worktree under the existing execution rules, and assess its output into findings like any other evidence: each confirmed problem becomes a normal finding with an anchor, trigger, and the full field set. IF the project documents no such stage; THEN record the sub-stage as not applicable in the **Verification assessment** and continue at sub-stage b. IF the documented tool cannot run in the review environment (missing dependencies, no network, no secrets); THEN record it as **unverified** — the existing execution rule for environment-blocked runs — not a finding against the change.

**b. Itemized quality checklist.** Apply the checklist below to the diff and attempt to construct breakage scenarios the extracted claims do not state. A checklist item yields a finding only when a trigger scenario can be constructed; an item with no constructable trigger is not a finding — record it as checked-and-clear in the **Verification assessment** (the do-not-invent rule).

- error handling: ignored or swallowed errors, missing cleanup/rollback on failure, partially applied changes
- resources: leaked handles, unbounded growth, missing timeouts or limits
- boundaries: unchecked assumptions about input size/shape, paths, cwd, environment, empty values; off-by-one
- structure: copy-paste that will drift, dead or unreachable code, hidden side effects, misleading names
- failure visibility: silent failure, logs or messages that misstate what happened
- tests: assertions that cannot fail, tests coupled to implementation details, missing failure-path coverage
- complexity: branches and conditions no claim or design decision justifies

Quality-stage findings enter the severity ladder and verdict mapping normally — they are findings with anchors and triggers like any other.

## Review questions

### Code and change quality

- Does each material work-item requirement and MR claim have implementation and validation evidence?
- What would have to be true for this implementation to be wrong?
- Can a small counterexample violate any claimed invariant?
- Are there hidden assumptions about input, CLI arguments, paths, cwd, environment, time, concurrency, subprocesses, errors, retries, or compatibility?
- What existing caller, invocation, artifact, or workflow could regress?
- Are tests aimed at externally visible boundaries, including failure paths, rather than only implementation details?
- Are the [defaults, fallbacks, and transformations](#defaults-fallbacks-and-transformations) checks satisfied, including any docs and tests they require?
- What changed code path processes input from a boundary the author may not have recognized as untrusted?

### Reporting, artifacts, and state

When the work writes reports, generated files, events, caches, indexes, migrations, or state:

- identify the canonical source of truth;
- trace each execution path from trigger to artifact;
- check direct versus wrapped invocation;
- check missing/default inputs;
- check failure/interruption;
- check concurrent runs;
- check that run/correlation IDs, status, paths, hashes, and ownership agree across artifacts;
- identify artifacts that can be stale, overwritten, partially written, duplicated, inconsistent, or silently omitted;
- verify that rebuild and migration paths produce representations compatible with normal runtime writes.

### Design decisions

For every relevant decision:

- explain why it applies;
- classify the result as **complies**, **possible tension**, **violates**, or **not applicable**;
- distinguish accepted/implemented decisions from proposed ones;
- identify required design/document updates when a contract changed.

Do not manufacture a design conflict merely because a decision document discusses the same area.


## Severity

Order findings by severity, highest first:

**Blocking → Important → Minor → Observation**

Give each finding a stable ID — `F1`, `F2`, … — assigned in output order (severity order, highest first; ties in discovery order). Print each finding under the heading `#### F<n> — <Severity>: <one-line summary>`. Outside this report (forge comments, later rounds), refer to a finding as `R<round>.F<n>`.

- **Blocking** — the change cannot ship: correctness break, contract violation, security or data-loss risk in the changed code, or the change fails its own stated goal. Merge is refused.
- **Important** — real, plausible defect or degradation with a workaround, or a required update (design/document/tests) that was skipped. Expected to be fixed before merge; the operator may decide otherwise at publication, on the record.
- **Minor** — quality or maintainability issues that do not threaten the main flow. Fix now or convert to a follow-up work item.
- **Observation** — informational, stylistic, or speculative-but-plausible notes. No verdict impact.

**Reachability caps severity.** A trigger must be reachable through the supported surface: documented API, normal invocation, realistic input. If the only trigger requires bypassing that surface — mutating internal state, skipping the registration/validation path, calling private helpers — cap the finding at **Minor**, and recommend narrowing the surface (readonly, frozen, unexported) in preference to handling the misuse. Upgrade only if the surface is intentionally public and documented as mutable; cite where.

An executed probe proves a trigger exists, not that it is reachable. State in **Trigger** whether the probe used only the supported surface.

### Likelihood

Every finding also carries a **likelihood** grade for its trigger scenario — how probable the trigger is under the current implementation. Likelihood is an independent axis: it does not shift or cap severity. The reachability rule above answers a different question (is the trigger on the supported surface) and is unchanged; a trigger may be reachable yet `very-unlikely`.

- `probable` — the trigger arises in normal operation of the supported surface;
- `unlikely` — the trigger requires unusual but realistic conditions;
- `very-unlikely` — the trigger requires contrived conditions or coincidences;
- `impossible (under current implementation)` — no constructable path produces the trigger.

A finding graded `impossible` is recorded, not raised as a defect: cap its severity at **Observation** and exclude it from the verdict mapping — the same role as the cross-model meta-finding and the hypothetical-concern rule. A plausible triggering path is required to raise it; an `impossible` finding documents that none exists.

Each finding must contain:

- **Anchor**: changed code or contract responsible for bringing the issue into scope;
- **Claim / expected behavior**;
- **Existing behavior**;
- **Trigger**: concrete minimal scenario that demonstrates or risks the problem;
- **Consequence**;
- **Evidence**;
- **Likelihood** — the trigger's grade per [Likelihood](#likelihood);
- **Recommended correction**.

Do not raise hypothetical concerns without a plausible triggering path.

## Verdict

Use the verdict appropriate to the selected mode:

- implementation: **satisfied / partially satisfied / not satisfied**;
- MR: **approve / approve with follow-ups / request changes**;
- reconciliation: **aligned / divergent**.

The MR and implementation verdicts follow from the findings, not from judgment:

| Highest severity among findings | MR verdict | Implementation verdict |
| --- | --- | --- |
| Blocking or Important | request changes | not satisfied (Blocking) / partially satisfied (Important) |
| Minor | approve with follow-ups | satisfied |
| Observation, or none | approve | satisfied |

### Claim coverage blocks the verdict (first review only)

In the first review, the verdict cannot pass while any extracted new claim is unmapped. The presence check's insufficient-testing findings are **blocking**: if any new claim has neither a mapped test/scenario nor an accepted waiver, the MR verdict cannot be approve (or approve with follow-ups) and the implementation verdict cannot be satisfied. The verdict row of the mapping table above is applied only to the remaining findings once no unmapped claim stands in the way.

No new severity class is introduced for this: the unmapped claim is the **insufficient testing** finding class defined in the presence check, and its verdict consequence is this blocking rule.

The same rule applies in **later reviews** to touched `coverage: review-only` claims (see *Locating review-only claims*): the unverified-behavior-change finding is graded exactly like the first-review rule — **insufficient testing**, no new severity class — and its verdict consequence is **blocking**: the verdict cannot approve (or approve with follow-ups) while the touched review-only claim has neither a fresh waiver re-decided for this review nor a new mapped test. Once no such claim stands in the way, the verdict row of the mapping table above is applied to the remaining findings.

### Waiver procedure (first review only)

An unmapped claim can be unblocked only by an explicit operator waiver:

1. The reviewer lists the unmapped claims in the review output (the insufficient-testing findings) and stops — the reviewer never grants the waiver.
2. The operator grants the waiver per claim (or per listed set). The waiver decision is recorded in the review output only — the review records that the waiver was granted, for which `claim-id[/enumeration-id]`, and by whom; it does not modify the reviewed work or its tests.
3. The waiver residue (`coverage: review-only`) is written by **the operator** — never the reviewer — **after the review is published**, as an annotation appended to the claim's record: the claim block in the committed test file carrying the claim (the annotation is operator-added residue, not part of the block's emitted three-field format). A claim without a test has no claim block and no committed record: its waiver lives in the review output only (step 2), the claim stays outside durable data, and it remains a fresh gap in every review that sees it. Residue on a record is a **warning label, not permission**: it marks the claim as currently evidenced only by review, and a later review that touches the claim's code must treat it as a fresh gap — the waiver never carries over (see the no-waiver-inheritance rule in the presence-check section).
4. With all listed claims mapped or waived, the verdict is decided by the mapping table above on the remaining findings.

The reviewer's blocking rule and the operator's waiver are deliberately separated: the reviewer blocks; only the operator unblocks.

If the verdict seems wrong for the findings, the severity is what needs revisiting — re-check it against the definitions and the reachability rule, and do not override the verdict.

Section headings and summary lines must match the verdict. The reviewer reports findings and severities; what the author must change is decided by the operator at publication (see the publish-review skill), so do not label findings "required" or "changes required".

Reconciliation has exactly two verdict states. **Aligned** means the work item, code, tests, documentation, and decisions agree on all material claims. Anything else is **divergent** — partial alignment is divergent with only Minor findings. Express how far the artifacts have drifted through finding severities, not through a third verdict state.

Do not invent findings. If an area has no finding, state what was checked, which falsification attempts were made, and why the evidence is sufficient.
