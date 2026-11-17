"""Plan then apply (D21). The plan is its audit row: nothing is kept in memory, so any process can apply it.

1. Without `confirm`, the action's `plan` runs. Its diff is hashed in canonical form and stored on a
   `planned` audit row with a random confirm value, and the member sees the counts and the first entries.
2. With `confirm`, the plan row must be this member's, for this server, action and input, younger than 15
   minutes and unused. The plan runs again: a different hash refuses the apply and returns the fresh plan.
3. A matching hash queues the core `apply` job, which runs the action and reports progress. Its audit row
   points at the plan's. It runs once: a failed apply is recorded and never retried blindly.
"""

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from teabot.core.queue import APPLY_HANDLER, NewJob, Queue
from teabot.core.registry import ActionFailed, Audit, CallRecord, Refused
from teabot.sdk import ActionContext, ActionError, ActionSpec, Actor, Diff, DiffEntry
from teabot.sdk.fields import UntrustedText

PLAN_AGE = timedelta(minutes=15)
PAGE = 20

INSERT_PLAN = """
INSERT INTO core.audit_log (guild_id, user_id, token_id, surface, action, input, risk, outcome, diff_hash, confirm)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, 'planned', $8, $9) RETURNING time + $10::interval
"""
FIND_PLAN = """
SELECT p.id, p.guild_id, p.user_id, p.action, p.input, p.diff_hash,
       p.time > now() - $2::interval AS fresh,
       EXISTS (SELECT 1 FROM core.audit_log a WHERE a.plan_id = p.id) AS used
FROM core.audit_log p WHERE p.confirm = $1 AND p.outcome = 'planned'
"""
INSERT_APPLY = """
INSERT INTO core.audit_log (guild_id, user_id, token_id, surface, action, input, risk, outcome, plan_id)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, 'started', $8) RETURNING id
"""
SET_JOB = "UPDATE core.audit_log SET job_id = $2 WHERE id = $1"
APPLY_ROW = "SELECT action, guild_id, user_id, token_id, surface, input FROM core.audit_log WHERE id = $1"


class ShownEntry(BaseModel):
    """A diff entry as the member sees it: without its key, which is for the apply only."""

    change: str
    target: UntrustedText
    detail: UntrustedText | None = None


class Planned(BaseModel):
    """What the member sees before anything changes. `stale` says an earlier plan no longer matched."""

    action: str
    counts: dict[str, int]
    entries: list[ShownEntry]
    total: int
    confirm: str
    expires_at: datetime
    stale: bool = False
    notes: list[UntrustedText] = []


class Queued(BaseModel):
    """A confirmed plan, applying as a job: follow it with `admin.job_status`."""

    job_id: int
    audit_id: int


@dataclass(frozen=True)
class ApplyRequest:
    """What the `apply` job reads back from its audit row."""

    action: str
    guild_id: int
    actor: Actor
    raw_input: dict[str, Any]


def entry_order(entry: DiffEntry) -> tuple[str, str, str, str]:
    return entry.change, entry.target, entry.detail or "", "" if entry.key is None else str(entry.key)


def canonical(diff: Diff) -> str:
    """The diff as JSON with its entries in a fixed order, so equal state always hashes the same. Every entry
    comes from one model, so its keys are always in the same order too."""
    # An entry without a key hashes as it did before keys existed, so plans made then stay valid.
    entries = [
        e.model_dump(mode="json", exclude={"key"} if e.key is None else None)
        for e in sorted(diff.entries, key=entry_order)
    ]
    return json.dumps(entries, separators=(",", ":"))


def diff_hash(diff: Diff) -> str:
    return hashlib.sha256(canonical(diff).encode()).hexdigest()


def _who(record: CallRecord) -> tuple[int, int, str | None, str, str, str, int]:
    actor = record.actor
    raw = json.dumps(dict(record.input))
    return record.guild_id, actor.user_id, actor.token_id, actor.via, record.action, raw, int(record.risk)


class Plans:
    """The registry's `PlanBook`."""

    def __init__(self, queue: Queue, audit: Audit) -> None:
        self.queue = queue
        self.db = queue.db
        self.audit = audit

    async def handle(
        self,
        spec: ActionSpec[Any, Any],
        ctx: ActionContext,
        data: BaseModel,
        record: CallRecord,
        confirm: str | None,
    ) -> BaseModel:
        diff = await self._diff(spec, ctx, data, record)
        if confirm is None:
            return await self.plan(record, diff)
        plan_id, stored = await self.check(record, confirm)
        if diff_hash(diff) != stored:
            await self.audit.single(record, "refused", "plan_stale")
            return (await self.plan(record, diff)).model_copy(update={"stale": True})
        return await self.queue_apply(record, plan_id, diff)

    async def _diff(
        self, spec: ActionSpec[Any, Any], ctx: ActionContext, data: BaseModel, record: CallRecord
    ) -> Diff:
        if spec.plan is None:
            raise RuntimeError(f"{spec.name} is destructive and has no plan")
        try:
            return await spec.plan(ctx, data)
        except ActionError as exc:
            await self.audit.single(record, "error", str(exc))
            raise ActionFailed(repr(exc), public_message=str(exc)) from exc
        except Exception as exc:
            await self.audit.single(record, "error", repr(exc))
            raise ActionFailed(repr(exc)) from exc

    async def plan(self, record: CallRecord, diff: Diff) -> Planned:
        confirm = secrets.token_urlsafe(16)
        expires_at: datetime = await self.db.fetchval(
            INSERT_PLAN, *_who(record), diff_hash(diff), confirm, PLAN_AGE
        )
        return Planned(
            action=record.action,
            counts=diff.counts,
            entries=[
                ShownEntry(change=e.change, target=e.target, detail=e.detail)
                for e in sorted(diff.entries, key=lambda e: (e.change, e.target))[:PAGE]
            ],
            total=len(diff.entries),
            confirm=confirm,
            expires_at=expires_at,
            notes=diff.notes,
        )

    async def check(self, record: CallRecord, confirm: str) -> tuple[int, str]:
        """The plan row's id and diff hash, or a refusal saying why this confirm value does not apply."""
        row = await self.db.fetchrow(FIND_PLAN, confirm, PLAN_AGE)
        if row is None:
            raise Refused("confirm_unknown", "there is no plan with that confirm value")
        same = (row["guild_id"], row["user_id"], row["action"]) == (
            record.guild_id,
            record.actor.user_id,
            record.action,
        )
        if not same or json.loads(row["input"]) != dict(record.input):
            raise Refused(
                "confirm_mismatch", "that plan was made by someone else, or for another action or input"
            )
        if not row["fresh"]:
            raise Refused("plan_expired", "that plan is more than 15 minutes old; ask for a new one")
        if row["used"]:
            raise Refused("plan_used", "that plan has already been applied")
        return row["id"], row["diff_hash"]

    async def queue_apply(self, record: CallRecord, plan_id: int, diff: Diff) -> Queued:
        async with self.db.transaction() as tx:
            audit_id: int = await tx.fetchval(INSERT_APPLY, *_who(record), plan_id)
            # The apply receives the diff the member confirmed, so it need not repeat the plan's queries.
            payload = {"audit_id": audit_id, "diff": diff.model_dump(mode="json")}
            user = record.actor.user_id
            job = NewJob(
                "core",
                APPLY_HANDLER,
                guild_id=record.guild_id,
                payload=payload,
                started_by=user,
                max_attempts=1,
            )
            job_id = await self.queue.schedule(job, within=tx)
            await tx.execute(SET_JOB, audit_id, job_id)
        return Queued(job_id=job_id, audit_id=audit_id)

    async def apply_request(self, audit_id: int) -> ApplyRequest:
        row = await self.db.fetchrow(APPLY_ROW, audit_id)
        if row is None:
            raise RuntimeError(f"no audit row {audit_id} to apply")
        actor = Actor(row["user_id"], row["surface"], row["token_id"])
        return ApplyRequest(row["action"], row["guild_id"], actor, json.loads(row["input"]))
