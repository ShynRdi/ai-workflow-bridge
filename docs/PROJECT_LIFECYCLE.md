# Project Lifecycle Protocol

## State machine

```text
SETUP
  │ PLAN PROJECT
  ▼
PLANNING
  │ AI_WORKFLOW_ROADMAP + READY_TO_ARM
  ▼
READY_TO_ARM
  │ ARM & RUN
  ▼
RUNNING ────────────────┐
  │                     │
  │ CHANGE COURSE       │ protected command / decision
  ▼                     ▼
CHANGE_REVIEW        WAITING_APPROVAL
  │ approve/reject      │
  └──────────────┬──────┘
                 ▼
              RUNNING
                 │ FINISH PROJECT
                 ▼
             FINISHING
                 │ final verification contracts
                 ▼
 AI_WORKFLOW_PROJECT_DONE
                 │
                 ▼
              COMPLETE
```

## Planning protocol

Planning is non-executable. The LLM returns a canonical roadmap block and `READY_TO_ARM`.

## Execution protocol

Every executable turn uses exactly one `AI_WORKFLOW` contract. The Bridge checks:

1. contract schema;
2. canonical roadmap position;
3. decision flag;
4. attachment requirements;
5. command policy;
6. user approval where required;
7. local execution evidence.

## Canonical transitions

The Bridge can automatically accept only the immediate next `(phase, stage)` tuple from the stored machine-readable roadmap.

Any other roadmap jump becomes a decision checkpoint.

## Course changes

User-requested direction changes use `AI_WORKFLOW_CHANGE_REVIEW`. Commands are forbidden during review. Approval can replace the stored canonical roadmap and phase/stage.

## Stage stop vs project done

- `<<<AI_WORKFLOW_STOP>>>`: stop the current execution loop cleanly; project may remain unfinished.
- `<<<AI_WORKFLOW_PROJECT_DONE>>>`: accepted only in FINISHING state and means project-wide closeout.
