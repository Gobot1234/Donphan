import json
from typing import Any, Optional

import asyncpg
from asyncpg import pool as asyncpg_pool


class Connection(asyncpg.Connection):
    ...


class Pool(asyncpg_pool.Pool):
    ...


class Record(asyncpg.Record):
    ...


_pool: Pool = None  # type: ignore


async def create_pool(dsn: str, **kwargs: Any) -> Pool:
    """Creates the database connection pool."""
    global _pool

    async def init(connection: asyncpg.Connection) -> None:
        await connection.set_type_codec('json', schema='pg_catalog', encoder=json.dumps, decoder=json.loads, format='text')
        await connection.set_type_codec('jsonb', schema='pg_catalog', encoder=json.dumps, decoder=json.loads, format='text')

    _pool = p = await asyncpg.create_pool(dsn, init=init, **kwargs)
    return p


class MaybeAcquire:
    """Async helper for acquiring a connection to the database.

    Args:
        connection (asyncpg.Connection, optional): A database connection to use
                If none is supplied a connection will be acquired from the pool.
    Kwargs:
        pool (asyncpg.pool.Pool, optional): A connection pool to use.
            If none is supplied the default pool will be used.
    """

    def __init__(self, connection: Optional[asyncpg.Connection] = None, *, pool: Optional[Pool] = None):
        self.connection = connection
        self.pool = pool or _pool
        self._cleanup = False

    async def __aenter__(self) -> Connection:
        if self.connection is None:
            self._cleanup = True
            self._connection = c = await self.pool.acquire()
            return c
        return self.connection

    async def __aexit__(self, *args):
        if self._cleanup:
            await self.pool.release(self._connection)
