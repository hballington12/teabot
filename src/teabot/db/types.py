"""Type aliases for asyncpg. Its classes are generic only in the stubs, so the aliases are lazy (PEP 695)."""

import asyncpg
from asyncpg.pool import PoolConnectionProxy

type Record = asyncpg.Record
type Conn = asyncpg.Connection[asyncpg.Record]
type Pool = asyncpg.Pool[asyncpg.Record]
type AnyConn = asyncpg.Connection[asyncpg.Record] | PoolConnectionProxy[asyncpg.Record]
