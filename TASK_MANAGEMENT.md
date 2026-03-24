# Task Management Process

This document defines how tasks are organized, planned, and executed in this project.

## Structure

```
tasks/
  phase-0/          # Project Scaffolding & Infrastructure
  phase-1/          # Acoustic Pre-Processing
  phase-2/          # Transcription & Forced Alignment
  phase-3/          # Semantic Duplicate Detection
  phase-4/          # Video Assembly & Rendering
  phase-5/          # Export & Interoperability (OTIO)
  phase-6/          # Programmatic Verification / QA
  phase-7/          # Web Frontend for Educator Review
  phase-8/          # Professor Profiling (V2)
  phase-9/          # ML Model Training (V3/V4)
```

Each phase folder contains individual `.md` files, one per task (e.g., `01-audio-extraction.md`).

## Task File Format

Every task file follows this template:

```markdown
# Task Title

Status: `pending`
Phase: N
Depends on: [list of task IDs this blocks on]

## Objective

What this task accomplishes and why it matters.

## Requirements

Concrete, specific requirements gathered from the grilling session.

## Implementation Notes

Technical decisions, library choices, and approach details filled in after grilling.

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2
```

**Statuses:** `pending` | `in-progress` | `done` | `blocked` | `cancelled`

## Workflow: What Happens Before and After Each Phase

### Before Starting a Phase

1. **Grilling session.** The AI asks the user targeted implementation questions for every task in the upcoming phase. These are not generic -- they are specific to the decisions that affect how the code gets written. Examples:
   - "What sample rate should we extract audio at -- 16kHz for Whisper compatibility or 44.1kHz for quality?"
   - "Should silence detection be configurable per-video or use a global threshold?"
   - "Do you want the CLI to support both single-file and batch modes from day one?"

2. **Requirements drift check.** Before grilling, the AI reviews what changed during the previous phase. Questions like:
   - "During Phase 1, we discovered X. Does this change how you want Phase 2 to work?"
   - "Any requirements from the PRD that you now think are unnecessary or need rethinking?"
   - "Did anything come up during implementation that adds new tasks?"

3. **Update task files.** Based on grilling answers, the AI updates the `Requirements`, `Implementation Notes`, and `Acceptance Criteria` sections of each task file in the phase. New tasks are added if grilling reveals missing work. Tasks are cancelled if no longer needed.

### During a Phase

1. The AI picks up tasks in dependency order within the phase.
2. Task status is updated to `in-progress` when work begins.
3. Task status is updated to `done` when all acceptance criteria are met.
4. If a task is blocked, status is set to `blocked` with a note explaining what's blocking it.

### After Completing a Phase

1. The AI verifies all tasks in the phase are `done` or `cancelled`.
2. A brief summary of what was built, any deviations from the plan, and any discoveries that affect future phases.
3. The next phase's grilling session begins.

## Dependency Graph

```
Phase 0 (Scaffolding)
    |
    v
Phase 1 (Audio Pre-Processing)
    |
    v
Phase 2 (Transcription & Alignment)
    |
    v
Phase 3 (Duplicate Detection)
    |
    +---> Phase 4 (Video Assembly) ---> Phase 6 (QA/Verification)
    |
    +---> Phase 5 (OTIO Export) ---> Phase 7 (Web Frontend)
    |
    +---> Phase 8 (Professor Profiling)
    |
    +---> Phase 9 (ML Training)
```

**Critical path:** Phases 0 -> 1 -> 2 -> 3 -> 4 produce a working end-to-end pipeline.

## Quick Reference

- **Start of session:** "Read TASK_MANAGEMENT.md and the current phase, tell me what's next"
- **Start a new phase:** AI runs grilling session first, updates tasks, then begins work
- **Mid-phase check-in:** AI shows current task statuses and picks up next task
- **Scope change:** Modify task files directly or tell AI to add/remove/update tasks
