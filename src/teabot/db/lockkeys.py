"""Advisory lock keys (D15, D40, spike S2). Every key uses the two-int form (namespace, id)."""

import hashlib

MIGRATION_NS = 7000
SHARD_NS = 7001
PLUGIN_NS = 7002


def plugin_key(plugin_id: str) -> int:
    """A stable signed 32-bit key: the first four bytes of the id's SHA-256 (S2)."""
    return int.from_bytes(hashlib.sha256(plugin_id.encode()).digest()[:4], "big", signed=True)


def objid_to_key(objid: int) -> int:
    """`pg_locks.objid` is unsigned; turn it back into the signed key that was locked."""
    return objid - 2**32 if objid >= 2**31 else objid
