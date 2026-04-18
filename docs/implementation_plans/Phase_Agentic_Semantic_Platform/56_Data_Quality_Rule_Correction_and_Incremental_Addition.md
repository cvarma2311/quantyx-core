# 56. Data Quality Rule Correction and Incremental Addition

## Goal

Handle two common rule-lifecycle problems cleanly in the data-quality workflow:

1. the user provides a batch of plain-English rules, but the system interprets some of them incorrectly
2. the user provides additional rules later and wants them added without losing the earlier validated set

This phase defines a versioned rule-source and rule-interpretation model so the backend can:

- preserve the original user intent
- show how the system interpreted the rules
- support correction and replay
- support incremental rule additions
- keep runs reproducible and auditable

---

## Problem 1: Initial Rule Interpretation Was Wrong

### Example

The user provides 25 rules in plain English during deployment.

The backend extracts and normalizes them, but 4 rules are not aligned with what the user meant.

Examples:

- the wrong table was bound
- the wrong column was chosen
- a referential rule was interpreted as a not-null rule
- a conditional rule was simplified too aggressively

### Risk

If the system directly treats the first interpretation as final:

- invalid rules may execute
- correct rules may be skipped
- trust score and dashboards become misleading
- the user has no clean correction path beyond retyping context and rerunning everything blindly

### Required Solution

Separate rule handling into three layers:

1. **Rule Source Version**
   - raw user-authored rule text exactly as submitted
   - versioned
   - immutable after creation

2. **Rule Interpretation Version**
   - canonical structured rules extracted from that source text
   - includes confidence, ambiguity markers, resolved table/column bindings, executor kind, and execution plan
   - versioned

3. **Rule Execution Run**
   - actual execution results for one specific interpretation version
   - linked back to the interpretation version used by the run

### Recommended Flow

1. User submits plain-English rules.
2. Backend stores the raw submission as a new `rule_source_version`.
3. Backend extracts structured candidate rules.
4. Backend stores a new `rule_interpretation_version`.
5. Backend exposes the parsed interpretation before or alongside execution:
   - accepted rules
   - low-confidence rules
   - ambiguous rules
   - unsupported rules
6. User corrects the plain-English text if needed.
7. Backend creates a new interpretation version rather than mutating the old one.
8. Backend replays the DQ rule execution against the corrected interpretation version.

### Backend Behavior

Correction should be handled as:

- **new source version**
- **new interpretation version**
- **new execution snapshot**

Do not overwrite old interpretation rows in place.

### Product Rule

The first extraction must not be the only durable representation of the user’s rules.

The original text must remain available for:

- audit
- explainability
- correction
- future re-interpretation with improved extraction logic

---

## Problem 2: User Adds More Rules Later

### Example

The user initially provides 25 rules.

Later they realize 5 more rules were missing and want to add them without discarding the earlier 25.

### Risk

If the backend only supports full replacement:

- previously validated rules may be lost
- every update becomes destructive
- users must resubmit the entire rule set each time
- audit becomes unclear

### Required Solution

Support explicit rule-set change operations:

- `append`
- `replace_all`
- `modify_existing`
- `disable_existing`

For this scenario, the user action is:

- `append`

### Recommended Flow

1. Active rule set version contains 25 rules.
2. User submits 5 additional rules in plain English.
3. Backend stores that new submission as a new source version.
4. Backend extracts the 5 new rules into a new interpretation version.
5. Backend compares them against the currently active rule set:
   - duplicate rule?
   - overlapping rule?
   - conflicting rule?
   - stricter or weaker variant of an existing rule?
6. Backend creates a new active rule-set version containing 30 rules.
7. Backend executes one of:
   - **delta-only execution** for the 5 newly added rules
   - **full replay** for all 30 rules if conflicts or broad recalculation are required

### Product Rule

Late rule additions should be additive by default, not destructive by default.

---

## Rule Lifecycle Model

### Core Concepts

#### 1. Rule Source Document

Stores the raw user-authored text.

Fields:

- `rule_source_id`
- `tenant_id`
- `domain_id`
- `run_scope_id` or `deployment_scope_id`
- `source_text`
- `submission_mode`
  - `initial_context`
  - `manual_addition`
  - `manual_correction`
- `change_operation`
  - `append`
  - `replace_all`
  - `modify_existing`
  - `disable_existing`
- `created_by`
- `created_at`
- `supersedes_rule_source_id`

#### 2. Rule Interpretation Set

Stores the structured rules extracted from one source document.

Fields:

- `rule_interpretation_set_id`
- `rule_source_id`
- `interpretation_version_no`
- `status`
  - `draft`
  - `ready_for_execution`
  - `superseded`
- `accepted_rule_count`
- `ambiguous_rule_count`
- `unsupported_rule_count`
- `low_confidence_rule_count`
- `created_at`

#### 3. Interpreted Rule Row

Each extracted rule becomes one structured row.

Fields:

- `interpreted_rule_id`
- `rule_interpretation_set_id`
- `rule_type`
- `table_name`
- `column_name`
- `reference_table`
- `reference_column`
- `condition_json`
- `source_text`
- `confidence`
- `executor_kind`
- `execution_plan_json`
- `interpretation_status`
  - `accepted`
  - `ambiguous`
  - `unsupported`
  - `low_confidence`
- `conflict_status`
  - `none`
  - `duplicate_of_existing`
  - `overlaps_existing`
  - `conflicts_existing`

#### 4. Active Rule Set

Defines the currently active rules for a tenant/domain/scope.

Fields:

- `active_rule_set_id`
- `tenant_id`
- `domain_id`
- `scope_kind`
  - `deployment`
  - `workspace`
  - `tenant_domain`
- `rule_interpretation_set_id`
- `activation_status`
  - `active`
  - `superseded`
- `created_at`

#### 5. Rule Execution Snapshot

Each DQ run should reference the exact active rule set used at execution time.

Fields:

- `quality_run_id`
- `run_id`
- `active_rule_set_id`
- `rule_interpretation_set_id`
- `execution_scope`
  - `delta_only`
  - `full_replay`

---

## Scenario A: Correcting Misinterpreted Rules

### Desired Backend Flow

1. User submits 25 rules.
2. Backend stores `rule_source_version_1`.
3. Backend creates `interpretation_version_1`.
4. User reviews parsed output and says some rules are wrong.
5. User edits the plain-English text.
6. Backend stores `rule_source_version_2`.
7. Backend creates `interpretation_version_2`.
8. Backend marks version 1 as superseded, not deleted.
9. Backend replays DQ rule execution using interpretation version 2.

### API Shape

#### Submit Rule Intake

```http
POST /data-quality/rule-intake
```

Request:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_123",
  "source_text": "Customer email must be present. Orders.customer_id must exist in customer.customer_id.",
  "change_operation": "replace_all"
}
```

#### Read Parsed Interpretation

```http
GET /data-quality/rule-intake/{rule_source_id}
```

Response should include:

- original source text
- interpreted rules
- confidence
- ambiguous rules
- unsupported rules
- compiled execution preview

#### Re-interpret After User Correction

```http
POST /data-quality/rule-intake/{rule_source_id}/re-interpret
```

Request:

```json
{
  "source_text": "Customer email must be present and valid. Orders.customer_id must exist in customer.customer_id.",
  "change_operation": "replace_all"
}
```

#### Replay Rule Execution

```http
POST /data-quality/runs/{run_id}/replay-rules
```

Request:

```json
{
  "rule_interpretation_set_id": "dq_rule_interp_002",
  "execution_scope": "full_replay"
}
```

---

## Scenario B: Adding 5 More Rules Later

### Desired Backend Flow

1. Active rule set contains 25 rules.
2. User submits 5 more rules.
3. Backend stores a new source document with `change_operation=append`.
4. Backend interprets the 5 new rules.
5. Backend checks for duplicates/conflicts against the active 25.
6. Backend produces a new active rule set version with 30 total rules.
7. Backend executes:
   - only the new 5 rules if safe
   - or full replay of all 30 if needed

### API Shape

#### Append Additional Rules

```http
POST /data-quality/rule-intake
```

Request:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_123",
  "source_text": "If country is India, pincode must be 6 digits. State must be present when country is India.",
  "change_operation": "append"
}
```

#### Activate New Rule Set

```http
POST /data-quality/rule-sets/activate
```

Request:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "base_active_rule_set_id": "dq_ruleset_025",
  "rule_interpretation_set_id": "dq_rule_interp_026",
  "activation_mode": "append"
}
```

#### Run Only Delta Rules

```http
POST /data-quality/runs/{run_id}/replay-rules
```

Request:

```json
{
  "active_rule_set_id": "dq_ruleset_030",
  "execution_scope": "delta_only"
}
```

---

## Conflict and Duplicate Handling

When rules are corrected or appended later, the backend must compare new interpreted rules against the currently active set.

### Possible Outcomes

#### Duplicate

The new rule is semantically the same as an existing active rule.

Action:

- mark as duplicate
- do not create a second active copy

#### Overlap

The new rule partly overlaps an existing rule.

Example:

- existing: `email must be valid`
- new: `customer.email must match email pattern`

Action:

- keep both as linked overlap candidates or collapse to canonical form

#### Conflict

The new rule contradicts the active rule.

Example:

- existing: `status must be one of Open, Closed`
- new: `status must be one of Open, Closed, Cancelled`

Action:

- mark conflict explicitly
- require user choice or precedence rule

---

## Execution Strategy

### Delta-Only Execution

Use when:

- only new rules were appended
- no conflicts were found
- earlier rules remain unchanged

Benefits:

- faster
- cheaper
- simpler operationally

### Full Replay

Use when:

- rules were corrected
- existing rules changed semantics
- rule conflicts were resolved
- trust score and DQ outputs need a clean full recomputation

Benefits:

- consistent final state
- easier to reason about reports and dashboards

### Product Rule

Correction usually implies **full replay**.

Append-only usually implies **delta-only execution first**, with optional full refresh afterward.

---

## UI / UX Guidance

The UI should not ask the user to choose low-level internal rule types.

The UI should expose:

1. original plain-English source text
2. interpreted rules
3. confidence and ambiguity markers
4. duplicates/conflicts/overlaps
5. change mode:
   - replace all
   - append
6. backend-generated execution preview

### Review States

Each interpreted rule should be visible as:

- accepted
- ambiguous
- unsupported
- conflicting
- duplicate

### Important UX Rule

When a user adds 5 rules later, the UI should frame it as:

- “Add to existing rule set”

not:

- “Re-enter all rules again”

---

## Recommended Early Implementation

To solve both scenarios early without overbuilding:

### Must Implement First

1. versioned raw rule-source storage
2. versioned interpreted rule-set storage
3. append vs replace-all operations
4. rule interpretation preview API
5. run snapshot linked to the exact rule-set version used
6. replay-rules API with:
   - `delta_only`
   - `full_replay`

### Can Come Later

1. manual approval UI for conflicts
2. advanced merge/canonicalization of overlapping rules
3. automatic semantic deduplication across older rule versions
4. tenant-wide reusable rule libraries

---

## Recommended DB Additions

New tables:

- `quantyx_data_quality_rule_sources`
- `quantyx_data_quality_rule_interpretation_sets`
- `quantyx_data_quality_interpreted_rules`
- `quantyx_data_quality_active_rule_sets`
- `quantyx_data_quality_rule_set_members`

Add to existing run table or summary:

- `active_rule_set_id`
- `rule_interpretation_set_id`
- `rule_execution_scope`

---

## Acceptance Criteria

### Scenario A

If the user corrects previously submitted rule text:

- the original source text remains stored
- a new interpretation version is created
- old interpretation remains auditable
- a new execution replay can be triggered against the corrected interpretation

### Scenario B

If the user adds 5 more rules later:

- existing active rules remain intact
- the new rules are appended through a new version
- duplicates/conflicts are detected
- delta-only execution is possible
- full replay remains available

---

## Summary

Both scenarios require the backend to stop treating rule extraction as a one-time destructive step.

The right model is:

- version the raw rule text
- version the interpreted structured rules
- version the active rule set
- link each run to the exact rule-set version it used

That solves:

- misinterpretation correction
- late rule additions
- replay
- audit
- explainability
- stable UI integration
