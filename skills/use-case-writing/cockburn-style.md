# Cockburn Style

Use this style by default. Write specifications using a simplified Alistair Cockburn use-case format — a tree model where the main scenario is the happy path and every alternative is a numbered extension.

This is the **default style**. Use it when the request doesn't explicitly specify a format.

---

## Overview — What Cockburn Style Looks Like

```
### Use Case: {Name}

_Main Success Scenario:_
1. First step
2. Second step with result; call it _namedResult_
3. Delegation step
   Call use case _Other Use Case_; provide _input_

_Extension / Failure Scenarios:_
1.a. IF condition; THEN
   1.a.1. Handle the condition
```

---

## Goal Levels

Cockburn classifies use cases by the altitude of the goal they capture:

- **Cloud:** the strategic goal of the whole enterprise — too high to groom.
- **Kite (summary/umbrella):** a goal spanning multiple actors or multiple sittings — a program or epic. Served by other use cases; nothing observable happens "in one sitting" at this level.
- **Sea level:** an actor's goal achieved in one sitting: one actor, one goal, an observable result when the sitting ends. The normal level for a story or task.
- **Underwater (subfunction):** steps that serve a sea-level goal but are never a goal in themselves — validate, parse, persist, log. Discovered during implementation, not groomed as use cases.

**Sea-level anchor test:** a use case anchors at sea level when it can be stated as *`<actor>` wants `<goal>` so that `<observable outcome>`* and the outcome is observable in one sitting. Failures:

- No single actor, or the outcome takes many sittings → a **kite**: write one umbrella summary use case, then groom sea-level children under it. Never groom the kite itself.
- The statement only makes sense as a step inside another use case ("validate the payload", "persist the record") → **underwater**: merge it upward into that use case's steps or extensions.

When in doubt, anchor at sea level and let extensions carry the detail — see below.

---

## Structure

### 1. Main Path / Extension Pattern

The main scenario is the happy path only. Every "else" or alternative becomes an extension scenario.

**Main Scenario:**
```
3. Convert _@type_ child node of _payload_ to string; call it _payloadType_
```

**Extension (handles the alternative):**
```
3.a. IF _payload_ is missing; THEN
   3.a.1. Log a warning; complete scenario
```

### 2. Tree Model and Extension Numbering

A use case is a tree. Each step in the main path is a node numbered with a single digit. Alternatives are siblings of their parent node, numbered `k.a`, `k.b` etc.

```
1. ── Step one
   |
  1.a. First alternative at step 1
  1.b. Second alternative at step 1
        |
2. ── Step two
        |
3. ── Step three
   |
  3.a. Alternative at step 3
        |
4. ── Step four
```

Key rule: an extension is attached to a step *about to be executed*, never to a step that has completed. Extensions check preconditions of their parent step — conditions that would prevent that step from executing usefully.

```
3. Extract _resourceOrderRef_ from the cancel order; call it _resourceOrderRef_

3.a. IF the cancel order has no _completionCallback_; THEN
   3.a.1. Log "No completion callback, skipping notification"
   3.a.2. Complete task successfully
```

### 3. Extension Numbering — Alternating Rule

Labels strictly alternate between numeric and alphabetic segments. Numeric segments identify steps on a main path (the happy path *at that level*). Alphabetic segments identify sibling alternatives at that level. This alternation repeats recursively without limit.

```
Segment type:   numeric · alpha · numeric · alpha · numeric ...

1.              Main path step
1.a.            Alternative at step 1            (alpha: sibling of 1)
1.a.1.          Sub-step within alternative 1.a  (numeric: sub-path of 1.a)
1.a.1.a.        Alternative at sub-step 1.a.1    (alpha: sibling of 1.a.1)
1.a.1.a.1.      Sub-step within 1.a.1.a          (numeric: sub-path of 1.a.1.a)
1.a.1.b.        Second alternative at 1.a.1      (alpha: sibling of 1.a.1)
1.b.            Second alternative at step 1     (alpha: sibling of 1)
2.              Next main path step
2.a.            Alternative at step 2
```

The parent of any node is always obtained by dropping its last segment. The type of any segment (main path vs. alternative) is always determined by whether it is numeric or alphabetic — regardless of depth.

Use `-` for empty extension scenarios.

### 4. Deep Nesting → Sub Use Case

When logic gets complex, extract to a separate use case:

```
5. Calculate the changed fields; call it _deltaEntity_
   Call use case _Discover changed fields of entity_; provide _event_ and _payloadType_
```

### 5. Success Variation Extensions

When a step can be satisfied through multiple paths where one is an optimization of another, document the authoritative path in the MSS and the shortcut as an extension.

**Key test:** Would a business person say "that's the same thing, just faster/cheaper/simpler"?

| Scenario | MSS Step | Extension |
|----------|----------|-----------|
| Caching | Retrieve from external API | IF cached copy valid, return cached value |
| Pre-computed | Run full pricing calculation | IF locked rate exists, use locked value |
| Simplified mode | Execute full validation pipeline | IF quick-mode enabled, validate minimum fields |
| Pre-approval | Execute approval workflow | IF pre-approved, skip to confirmation |
| Incremental | Rebuild entire index | IF delta available, apply delta only |

```
_Main Success Scenario:_
k. Calculate _shippingCost_ for _order_
   - Fetch rates from carrier API
   - Apply dimensional weight formula

k.a. IF _order_ has locked shipping rate; THEN
   k.a.1. Set _shippingCost_ to _lockedRate_
   k.a.2. Skip to step k+1
```

---

## Flow Control Patterns

### When to Use Extension vs Multi-Branch

| Pattern | Use When | Common Examples |
|---------|----------|-----------------|
| **Multi-branch MSS** | Both paths are equally valid business outcomes | Credit card vs bank transfer |
| **Extension with early-exit** | One path is the goal, other is an edge case | "Initialize if necessary" — already done |
| **Extension with step skip** | Condition determines which subsequent steps run | Partial update vs full processing |
| **Extension with loop back** | Retry or re-validation needed | Re-queue for later processing |

### Early-Exit Conditions

```
1. Retrieve fulfillment record for _orderId_

1.a. IF record already exists; THEN
   1.a.1. Log "Already initialized"
   1.a.2. Skip to step 5 (complete scenario)
```

### Skipping Steps (Jumping Forward)

```
_Main Success Scenario:_
1. Load order details
2. Validate order completeness
3. Calculate pricing
4. Apply discounts
5. Persist order

2.a. IF order is flagged for quick processing; THEN
   2.a.1. Validate minimal fields only
   2.a.2. Skip to step 5 (bypass pricing and discounts)
```

**Documenting skips:** Always state "Skip to step N" or "Continue at step N" to make the jump explicit.

### Looping Back (Jumping Backward)

```
3. Validate _itemData_

3.a. IF validation fails due to stale data; THEN
   3.a.1. Refresh _itemData_ from source
   3.a.2. Retry from step 1

3.b. IF validation fails due to invalid input; THEN
   3.b.1. Log validation errors
   3.b.2. Complete scenario with failure status
```

### Anti-Pattern: GOTO Anywhere

Extensions SHOULD jump to specific named steps. The jump target should be meaningful.

**Avoid:**
```
1.a. IF condition; THEN skip to step 3   <- step 3 is what? why?
```

**Prefer:**
```
1.a. IF order already confirmed; THEN
   1.a.1. Skip to step 5 (finalize processing)
```

---

## Conditional Outcomes (Non-Error)

When a step produces multiple equally-valid business outcomes:

```
_Main Success Scenario:_
1. Evaluate _resourceStatus_
2. IF _resourceStatus_ equals "available"
   THEN Prepare immediate allocation; call it _allocationResult_
   ELSE IF _resourceStatus_ equals "reserved"
   THEN Prepare reservation transfer; call it _allocationResult_
   ELSE Prepare queue for next available; call it _allocationResult_
```

---

## Extended Patterns

### Data Extraction from Structured Sources

**Inline Extraction:**
```
3. Extract _serviceId_ from _orderPayload_ at path $.orderItem[?(@.id=='{_orderItemId_}')].service.id
4. Parse _rawJson_ as JSON; call it _orderData_
```

**Extraction with Condition:**
```
5. Find the entity in _orderData.item[]_ where _id_ equals _orderItemId_; call it _matchingItem_
   Extract _serviceId_ from _matchingItem.service.id_
```

### External System Interactions

**REST GET:**
```
3. Call _inventoryService.getResource_ with _resourceId_; call it _resourceData_
```

**REST POST:**
```
4. Call _activationService.createService_ with _activationRequest_; call it _createdService_
   Extract _serviceId_ from _createdService.id_
```

**REST PATCH:**
```
5. Call _orderService.patchOrder_ with _orderId_ and _patchPayload_
```

### Data Transformations

**With Named Template:**
```
4. Transform _inputData_ using template _conversionTemplate_; call it _transformedData_
```

**With Context Variables:**
```
5. Transform _servicePayload_ using template _activationTemplate_ with variables:
   - _targetId_ = _serviceId_
   - _targetName_ = _serviceName_
   Call it _activationRequest_
```

**Inline Mapping:**
```
3. Map _sourceEntity_ fields to _targetEntity_:
   - _sourceId_ → _targetId_
   - _sourceName_ → _targetName_
   Call it _mappedEntity_
```

### State Transitions

**Simple:**
```
3. Update _fulfillmentStatus_ to "completed"
```

**Conditional with Side Effects:**
```
4. Update _resourceStatus_ to _targetStatus_
   IF _targetStatus_ equals "assigned"
   THEN ALSO set _startDate_ to current timestamp
```

### Lookup Patterns with Fallback

**With Default:**
```
2. Retrieve _configuration_ for _tenantId_; if not found, use _defaultConfiguration_; call it _effectiveConfig_
```

**With Exception:**
```
2. Retrieve _fulfillmentContext_ using _orderId_ and _orderItemId_
   IF not found; THEN throw _NotFoundException_
```

**Conditional Retrieval:**
```
1. Check if _context_ exists for _identifier_
2. IF exists; THEN retrieve _existingData_; call it _result_
   ELSE initialize new _result_ with defaults
```

---

## Extension-First Precision

Precision in a specification comes primarily from **enumerating extensions**, not from densifying the main path. The main scenario stays a thin happy-path spine; the edge cases — "closed then reopened", "reviewer requests changes", "merge conflicts" — are named as extensions in the `k.a` format above. If a groomed use case feels imprecise, the fix is to enumerate more extensions, not to add detail to the main scenario.

## One-Sentence Summary

Keep the main scenario as the tree's happy-path spine, push every alternative to a sibling extension with alternating numeric/alpha numbering, extract deep branches into sub use cases, and anchor every use case at sea level — precision comes from enumerated extensions, not from a densified main path.
