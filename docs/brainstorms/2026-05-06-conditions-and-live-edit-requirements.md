---
title: First-class Conditions + reactive live-edit
type: requirements
status: ready-for-planning
date: 2026-05-06
origin_session: ce-brainstorm 2026-05-06
---

# Requirements: First-class Conditions + reactive live-edit

## Problem Frame

Lab protocols often run as multiple **conditions** in parallel during one experimental session. Each condition is a sequence of timed steps (treat → incubate → wash → re-incubate → image). Conditions can share suffixes ("same as Condition 1 from the wash onward") or be totally independent shapes. Some steps share scarce resources (the microscope can only image one dish at a time), creating scheduling conflicts that the system already detects (audit-findings U6) but can only express against a flat, ungrouped step list.

The current data model treats an Experiment as a flat set of Steps with no grouping. To run two conditions today, the user creates two unrelated Experiments and reasons about them separately. The Runner doesn't visualize parallel timing, doesn't accommodate the unique mid-step time-accounting mechanic the protocols use ("the wash time eats into the next incubation's countdown"), doesn't issue pre-warnings before a step ends, and doesn't have a tablet-first focus-mode UI suitable for at-the-bench use.

This doc captures the next plan's scope: introduce a first-class **Condition** abstraction inside Experiments, add the small set of mechanics that the lab use case demands (cascading time, pre-warnings, two reactive live-edit operations), and ship a tablet-first focus-mode UI. Safe-window math (Goal 4 part 2) and the calendar/Gantt visualization (Goal 3) are explicitly deferred to follow-up plans.

---

## Actors

- **A1 Experiment Designer** (web). Authors a session containing one or more Conditions, each with a sequence of Steps and resource requirements.
- **A2 Experiment Runner** (web, at the bench). Operates the experiment; clicks START/PAUSE/COMPLETE per step; makes mid-run adjustments when reality drifts from the plan.
- **A3 Mobile Operator** (tablet/phone, at the bench). A stripped-down version of A2: sees the active step on one condition, presses a big button, swipes between conditions to check timing on others. Receives notifications and pre-warnings.

---

## Key Flows

- **F1 Design a multi-condition session.** Designer creates Experiment, defines Conditions (name, color), drops Steps into each Condition with type/duration/resource. Saves; system runs conflict detection (already shipped) and surfaces warnings.
- **F2 Run a session at the bench.** Operator clicks START on Condition 1's first step at wall-clock time T0. Later, clicks START on Condition 2's first step at wall-clock time T1. The Runner shows both Conditions as swimlanes with the active step on each highlighted.
- **F3 Cascading time across steps.** A TASK step (e.g., "wash") accumulates `elapsed_time` during the user-driven activity. When the operator clicks START on the next step, that next step's `elapsed_time` initializes from the wash's final elapsed; its countdown begins partly consumed (e.g., a 30-min step shows "26:00 remaining" if wash took 4 min).
- **F4 Pre-warning before step end.** A FIXED_DURATION or AUTOMATED_TASK step has an optional list of pre-warning offsets (e.g., 10 min before end). When fired, the operator receives a notification + a prominent message in the Runner / Mobile view.
- **F5 Live-edit during the run.** Operator extends/shrinks the active step's duration, or pushes an entire Condition's remaining schedule by N minutes (e.g., "Dish 4 was delayed 10 min"). Conflict detection re-runs; warnings render inline.
- **F6 Mobile focus mode.** Operator opens the experiment on a tablet/phone. UI shows ONE condition at a time: big START/PAUSE/COMPLETE button for the active step, message area above, prominent countdown. Swipe (or arrow buttons) cycles to next/previous condition. Pre-warnings + notifications interrupt with full-screen alerts.

---

## Acceptance Examples

- **AE1 (covers F1, F4, R1, R6).** Designer creates "Cell stress assay" with two conditions:
  - **Condition A**: NaAsO2 / 60-min FIXED_DURATION → Wash / TASK → Re-incubate / 30-min FIXED_DURATION (10-min pre-warning) → Image / 20-min AUTOMATED_TASK (microscope).
  - **Condition B**: Nocodazole / 60-min FIXED_DURATION → NaAsO2 / 60-min FIXED_DURATION → Wash / TASK → Re-incubate / 30-min FIXED_DURATION (10-min pre-warning) → Image / 20-min AUTOMATED_TASK (microscope).
  Save returns successfully; the conflict report flags the two microscope steps if their scheduled windows overlap.
- **AE2 (covers F3, R3).** Operator runs Condition A. NaAsO2 step completes after 60 min. They click START on Wash; wash takes 4 min; click COMPLETE on Wash. Click START on Re-incubate. Re-incubate's countdown immediately shows **26 min remaining** (30 - 4) because Wash is configured to cascade its elapsed time into Re-incubate.
- **AE3 (covers F4, R4).** During the 30-min Re-incubate step, at 20 min elapsed (10 min before end), the operator receives a "Bring dish to microscope" notification; on the Mobile view, a full-screen alert appears with the message.
- **AE4 (covers F5, R5).** During Condition A's Re-incubate step, the operator extends it by 5 minutes via a "+5 min" control in the Runner. The step's expected end time updates; conflict detection re-runs and surfaces a new warning if the microscope window now overlaps with Condition B's microscope window.
- **AE5 (covers F6, R7).** Operator opens the experiment on a tablet, lands on Condition A's current step with a big START button, swipes left to see Condition B's current step + countdown, swipes back. A pre-warning triggers; the screen shows the warning message until acknowledged.

---

## Requirements

- **R1 Conditions as first-class entity.** An Experiment has many Conditions. Each Condition has `id`, `name`, optional `color`, optional `description`, and an order index for display. Steps belong to a Condition (`condition_id` foreign key). Existing single-condition Experiments are auto-migrated to have one default Condition (e.g., named "Main") containing their existing Steps. **Cross-condition step dependencies are not allowed in v1** — Step.dependencies must reference Steps in the same Condition.
- **R2 Designer UI for Conditions.** The Designer adds a Conditions sidebar (or top-tab area). Users can create, rename, color, reorder, and delete Conditions. Each Step in the Designer is assigned to a Condition via dropdown or drag. The conflict-warning UI (already shipped) must label conflicts with the condition names, not just the step names — so "Microscope conflict between Condition A: Image and Condition B: Image" is readable.
- **R3 Cascading time between adjacent steps.** A Step has an optional `inherits_elapsed_from` field — either a sibling step ID within the same Condition, or the keyword `"previous"` meaning "the immediately preceding step in this Condition's order." When the operator clicks START on this step (and the referenced step has `actual_end_time` set), the new step's `elapsed_time` initializes from the referenced step's final `elapsed_time`. The Runner countdown reflects the inherited start. Cascading is **opt-in per step**, not the default.
- **R4 Pre-warnings.** A Step has an optional list of `prewarning_offsets_seconds` (e.g., `[600]` for "10 min before end", or `[600, 60]` for "10-min and 1-min warnings"). When a step is RUNNING and the wall clock reaches `step.expected_end - offset`, a notification fires via the U7 NotificationService, and the Runner / Mobile view renders the warning message prominently. Designer UI lets the user set offsets per step (chip input or simple add/remove rows).
- **R5 Reactive live-edit during a run.** The Runner exposes two controls for the active step: **+N min / -N min** (extend or shrink remaining duration; the system updates `duration_seconds` and recomputes scheduled times for downstream steps in the same Condition) and **Push condition by N min** (slides ALL pending/ready steps in this Condition's remaining schedule forward by N min). Both operations re-run conflict detection and persist via existing PUT/socket flows.
- **R6 Conflict detection works across Conditions within an Experiment.** The U6 detector already operates over all steps in an Experiment; this requirement is a non-regression promise. The conflict payload must additionally include `condition_a_id`, `condition_b_id`, `condition_a_name`, `condition_b_name` so the UI can label conflicts clearly.
- **R7 Mobile focus mode.** A new layout for tablet/phone optimized for at-the-bench use: shows ONE Condition at a time, with the active step's big start/pause/complete/skip button (sized for thumb tap), a message area above, and a prominent countdown. Swipe gestures (or chevron buttons) cycle between Conditions. Receives the same socket notifications as the web Runner. Pre-warnings render as full-screen interrupts requiring acknowledgment. (The exact route — extend `/watch/:id`, add `/mobile/:id`, or use responsive layout on `/run/:id` — is a planning decision.)

---

## Scope Boundaries

### Deferred for later

- **Safe-window math (Goal 4 part 2).** Computing `latest_safe_start` / `earliest_safe_start` per upcoming step ("you can delay this until 14:32 without conflict"). This is the most-requested follow-up; explicitly the next plan after this one.
- **Calendar / Gantt visualization (Goal 3).** Becomes mostly trivial once Conditions are first-class (one swimlane per Condition). Planned as the plan after safe-window math.
- **Cross-experiment scheduling.** Conflict detection still operates within a single Experiment in this plan. Cross-experiment ("today's session has experiments A and B both wanting the microscope") is a future feature.
- **Shared protocol fragments / step composition.** "Same as Condition 1 from the wash onward" is supported via copy-paste at design time, not via shared step references that auto-update. Shared identity is risky (silently affects multiple conditions); deferred.
- **Mid-run insert of unplanned steps.** Out of scope; the live-edit operations in this plan are limited to extend/shrink/push.
- **Stagger / start-offset metadata on Conditions.** Conditions don't carry an explicit `start_offset` field; they stagger naturally when the operator clicks START on each Condition's first step at the appropriate wall-clock time. Revisit when the Gantt view exposes an authoring need for offsets.
- **PWA install flow / offline support on mobile.** Out of scope; mobile focus mode is web-only for v1.

### Outside this product's identity

- **Generic project planner / Gantt tool.** runtimex is a lab-bench timer with scheduling. Conditions are protocol replicates, not arbitrary task groups.
- **LIMS / inventory / sample tracking.** No reagent inventory, no chain of custody, no sample IDs beyond Condition names.
- **Multi-lab tenancy / org accounts.** Single-user + per-user share is the model; no team workspaces in this scope.

---

## Key Decisions

- **Conditions are not required for new Experiments.** New experiments can have a single default "Main" Condition; the user opts into multi-condition design when they need it. Migration of existing data preserves single-condition shape.
- **Cascading time is per-step opt-in.** Resetting elapsed time on each step start is the safe default; cascading is the special biology-clock case for Wash → Re-incubate type chains.
- **Pre-warnings are step attributes, not a separate scheduling layer.** The notification fires when wall-clock reaches `step.expected_end - offset`. No new entity.
- **Live-edit operations are bounded for v1**: extend/shrink active step + push whole condition by N min. Mid-run insert and arbitrary reposition are deferred.
- **Mobile focus mode reuses the existing route system** — exact path (`/watch/:id` extension vs. responsive `/run/:id` vs. new `/mobile/:id`) is a planning decision, not a product decision.
- **Cross-condition step dependencies are not allowed in v1.** Dependencies stay within a Condition. Reduces planning complexity; revisit if a real use case appears.

---

## Dependencies / Assumptions

- **U6 conflict detection** continues to operate per-experiment and remains correct after Conditions are introduced. R6 is a non-regression promise.
- **U7 NotificationService** is the delivery channel for pre-warnings; no new notification type is needed (extend `step_timeout` factory or add a `step_prewarning` factory in planning).
- **Frontend stack** stays on CRA + MUI 5 for this plan. Mobile focus mode is built within that constraint.
- **Step type enum** (FIXED_DURATION, TASK, AUTOMATED_TASK, FIXED_START) covers the cases — no new types required.
- **The wash → re-incubate cascade pattern** is the primary motivating case for `inherits_elapsed_from`; the field design should be general enough that other "biology clock" patterns in future protocols also fit.

---

## Open Questions for Planning

- **Data migration shape**: should `condition_id` on Step be NOT NULL (with a backfill creating a "Main" Condition per existing Experiment) or nullable (cheaper migration, slightly messier model)?
- **Pre-warning storage**: list column on Step (JSON / array of integers) vs. separate `StepPrewarning` table? Cardinality is low (typically 0–2 per step) so a list column is probably right, but worth a planning-time decision.
- **Mobile route**: extend `/watch/:id`, add `/mobile/:id`, or detect viewport on `/run/:id` and swap layout? Resolve in planning.
- **"Push condition by N min" semantics**: does it shift only steps whose status is PENDING/READY, or also recompute future steps that have dependencies? Probably the former (don't touch RUNNING/COMPLETED), but confirm.
- **Color picker UX for Conditions**: predefined palette (8–12 colors) vs. free-form? Predefined is simpler and avoids accessibility/contrast pitfalls; recommend predefined unless a strong reason emerges.
- **Cross-condition step move in Designer**: if the user reassigns a Step from Condition A to Condition B, do dependencies break? Likely yes (R1 forbids cross-condition deps); the Designer should warn before the move strips dependencies.

---

## Sources

- ce-brainstorm session 2026-05-06.
- User's mock-experiment example (NaAsO2 protocol with cascading wash time, plus Nocodazole-prefixed variant).
- Existing repo at PR #1 merge (U1–U8 of audit-findings plan landed on `main`).
- `docs/plans/2026-05-06-001-fix-audit-findings-plan.md` — for the U6 conflict detector and U7 notification wiring this plan builds on.
