# Confirming changes

Some actions change a lot at once, or are hard to undo, such as cancelling a giveaway. Before teabot runs one, it shows you a **plan** of what will change, and waits for you to confirm it.

## What you see

Run an action like `/giveaways cancel giveaway:3`. teabot replies, privately, with the plan:

```text
Plan: giveaways.cancel
Nothing has changed yet. Confirm within 15 minutes to apply it.

Changes        cancel: 1
First entries  cancel A Discord Nitro
               [ Confirm ]
```

1. Read the plan. Nothing has changed yet.
2. If it is right, choose **Confirm**.
3. teabot replies `Applying.`, with a command to follow its progress, such as `/admin job_status job_id:12`.

If the plan is wrong, do nothing. It expires after 15 minutes.

## The rules

- You have 15 minutes to confirm.
- Only the member who ran the action can confirm its plan, and each plan can be confirmed once.
- Your permissions are checked again when you confirm.

## A stale plan

If something the plan shows changes before you confirm, teabot applies nothing. It shows you a fresh plan instead, which says:

```text
The target has changed since your last plan, so nothing was applied. This is the fresh plan.
```

Read the new plan, and confirm it if it is right.

An AI assistant gets the same plan, and is told to show it to you and wait for your agreement before it confirms.

**Next:** [The audit log](audit.md).
