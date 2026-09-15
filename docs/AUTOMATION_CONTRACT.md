# AI Workflow Bridge Protocol

## 1. Planning roadmap

Planning is non-executable and must include:

```text
<<<AI_WORKFLOW_ROADMAP>>>
{
  "phases": [
    {"id":"CP-0","title":"Foundation","stages":["BOOTSTRAP","VERIFY"]}
  ]
}
<<<END_AI_WORKFLOW_ROADMAP>>>
READY_TO_ARM
```

The Bridge stores this roadmap and validates later phase/stage transitions.

## 2. Executable workflow contract

Every assistant response that should advance local execution ends with exactly one contract:

```text
<<<AI_WORKFLOW>>>
{
  "version": 1,
  "phase": "CP-0",
  "stage": "BOOTSTRAP",
  "summary": "Inspect repository state",
  "decision_required": false,
  "decision_reason": "",
  "downloads": [],
  "commands": [
    {"cmd":"git status --short","cwd":".","purpose":"inspect repository"}
  ],
  "success_conditions": ["git status completes successfully"],
  "next_step": "continue bootstrap"
}
<<<END_AI_WORKFLOW>>>
```

Rules:
- prose is never executable;
- one atomic shell command per `commands[]` entry;
- protected commands require approval;
- blocked commands never run;
- generated files must be declared in `downloads` and referenced through `${AI_WORKFLOW_DOWNLOAD_DIR}`;
- roadmap transitions are accepted automatically only when they are the immediate next canonical position.

## 3. Course-change review

A user-requested change in direction is reviewed without commands:

```text
<<<AI_WORKFLOW_CHANGE_REVIEW>>>
{
  "summary": "Replace queue architecture",
  "impact": "Existing API remains; worker layer changes",
  "recommended": "Approve with a revised stage sequence",
  "proposed_phase": "CP-2",
  "proposed_stage": "QUEUE-REDESIGN",
  "roadmap_changes": ["replace Redis queue stage"],
  "replacement_roadmap": {
    "phases": [
      {"id":"CP-2","title":"Core runtime","stages":["QUEUE-REDESIGN","VERIFY"]}
    ]
  }
}
<<<END_AI_WORKFLOW_CHANGE_REVIEW>>>
```

No commands run until the human approves or rejects the review.

## 4. Clean execution stop

```text
<<<AI_WORKFLOW_STOP>>>
```

This stops the current execution loop but does not mean the project is globally complete.

## 5. Project completion

Only after **FINISH PROJECT** and final required verification:

```text
<<<AI_WORKFLOW_PROJECT_DONE>>>
```

The Bridge then enters `COMPLETE` and stops.
