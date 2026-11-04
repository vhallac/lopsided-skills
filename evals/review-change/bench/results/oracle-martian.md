---
schema: review-report/1
label: oracle
round: 1
target: https://github.com/calcom/cal.com/pull/14943
forge: github
repo: calcom/cal.com
mode: change
base: '0000000000000000000000000000000000000000'
head: '0000000000000000000000000000000000000000'
verdict: request-changes
findings:
- id: F1
  severity: Important
  likelihood: probable
  summary: "Using retryCount: reminder.retryCount + 1 reads a possibly stale value\
    \ and can lose increments under concurrency; consi\u2026"
- id: F2
  severity: Important
  likelihood: probable
  summary: "The deletion logic in scheduleSMSReminders.ts incorrectly deletes non-SMS\
    \ workflow reminders (e.g., Email, WhatsApp) th\u2026"
unrelated: []
prior: []
waivers: []
---

# Review — oracle for https://github.com/calcom/cal.com/pull/14943

## Findings

#### F1 — Important: Using retryCount: reminder.retryCount + 1 reads a possibly stale value and can lose increments under concurrency; consi…

- **Anchor:** `unknown-file:1-1`
- **Claim / expected:** Using retryCount: reminder.retryCount + 1 reads a possibly stale value and can lose increments under concurrency; consider an atomic increment via Prisma (increment: 1) to avoid race conditions (also applies to the similar update in the catch block).
- **Existing behavior:** as described above.
- **Trigger:** described above.
- **Consequence:** described above.
- **Evidence:** martian golden replay.
- **Likelihood:** probable
- **Recommended correction:** n/a (oracle).

#### F2 — Important: The deletion logic in scheduleSMSReminders.ts incorrectly deletes non-SMS workflow reminders (e.g., Email, WhatsApp) th…

- **Anchor:** `unknown-file:1-1`
- **Claim / expected:** The deletion logic in scheduleSMSReminders.ts incorrectly deletes non-SMS workflow reminders (e.g., Email, WhatsApp) that have retryCount > 1. This occurs because the retryCount condition within the OR clause for deletion lacks a method: WorkflowMethods.SMS filter, causing it to apply to all reminder types instead of only SMS reminders, which is the intended scope of this function.
- **Existing behavior:** as described above.
- **Trigger:** described above.
- **Consequence:** described above.
- **Evidence:** martian golden replay.
- **Likelihood:** probable
- **Recommended correction:** n/a (oracle).
