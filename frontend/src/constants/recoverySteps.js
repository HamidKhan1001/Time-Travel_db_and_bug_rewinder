/**
 * Recovery steps shown in the progress stepper (labels from the Console Review design).
 * `tool` is the matching backend tool from PRD §6 (timetravel/tools.py) — provisional mapping,
 * confirm with the backend team.
 */
export const recoverySteps = [
  { id: 'snapshot-fork', label: 'Snapshot Fork', tool: 'rewind_branch' },
  { id: 'replay-mutex', label: 'Replay Mutex', tool: 'extract_delta' },
  { id: 'state-reconstruct', label: 'State Reconstruct', tool: 'plan_merge' },
  { id: 'conflict-scan', label: 'Conflict Scan', tool: 'plan_merge' },
  { id: 'merge-plan', label: 'Merge Plan', tool: 'plan_merge' },
  { id: 'patch-verify', label: 'Patch Verify', tool: 'diagnose_and_patch' },
  { id: 'sandbox-test', label: 'Sandbox Test', tool: 'diagnose_and_patch' },
  { id: 'promote-live', label: 'Promote Live', tool: 'apply_recovery' },
]

/** Number of steps the agent runs on the clone before it waits for human approval. */
export const STEPS_BEFORE_APPROVAL = 7
