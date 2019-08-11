import inspect
from collections.abc import Iterable
from typing import Any, Dict, Iterable, List, Optional, Tuple

import asyncpg

from .connection import MaybeAcquire
from .column import Column
from .sqltype import SQLType


class _TableMeta(type):

    def __new__(cls, name, parents, dct, **kwargs):

        # Set the DB Schema
        dct.update({
            'schema': kwargs.get('schema', 'public'),
            '_columns': {}
        })

        table = super().__new__(cls, name, parents, dct)

        for _name, _type in dct.get('__annotations__', {}).items():

            # If the input type is an array
            is_array = False
            while isinstance(_type, list):
                is_array = True
                _type = _type[0]

            if inspect.ismethod(_type) and _type.__self__ is SQLType:
                _type = _type()
            elif not isinstance(_type, SQLType):
                _type = SQLType.from_python_type(_type)

            column = dct.get(_name, Column())
            column._update(table, _name, _type, is_array)

            table._columns[_name] = column

        return table

    def __getattr__(cls, key):
        if key == '__name__':
            return f'{cls.__name__.lower()}'

        if key == '_name':
            return f'{cls.schema}.{cls.__name__.lower()}'

        if key in cls._columns:
            return cls._columns[key]

        raise AttributeError(f'\'{cls.__name__}\' has no attribute \'{key}\'')


class Table(metaclass=_TableMeta):
    """A Pythonic representation of a database table.

    Attributes:
        _name (str): The tables full name in `schema.table_name` format.

    """

    @classmethod
    def _validate_kwargs(cls, primary_keys_only=False, **kwargs) -> Dict[str, Any]:
        """Validates passed kwargs against table"""
        verified = {}
        for kwarg, value in kwargs.items():

            if kwarg not in cls._columns:
                raise AttributeError(
                    f'Could not find column with name {kwarg} in table {cls._name}')

            column = cls._columns[kwarg]

            # Skip non primary when relevant
            if primary_keys_only and not column.primary_key:
                continue

            # Check passing null into a non nullable column
            if not column.nullable and value is None:
                raise TypeError(
                    f'Cannot pass None into non-nullable column {column.name}')

            def check_type(element):
                return isinstance(element, (column.type.python, type(None)))

            # If column is an array
            if column.is_array:

                def check_array(element):

                    # If not at the deepest level check elements in array
                    if isinstance(element, (List, Tuple)):
                        for item in element:
                            check_array(item)

                    # Otherwise check the type of the element
                    else:
                        if not check_type(element):
                            raise TypeError(
                                f'Column {column.name}; expected {column.type.__name__ }[], recieved {type(element).__name__}[]')

                # Check array depth is expected.
                check_array(value)

            # Otherwise check type of element
            elif not check_type(value):
                raise TypeError(
                    f'Column {column.name}; expected {column.type.__name__}, recieved {type(value).__name__}')

            verified[column.name] = value

        return verified

    # region SQL Queries

    @classmethod
    def _query_drop_table(cls, cascade: bool = False) -> str:
        """Generates the DROP TABLE stub."""
        return f'DROP TABLE IF EXISTS {cls._name}{" CASCADE" if cascade else ""}'

    @classmethod
    def _query_create_schema(cls) -> str:
        """Generates the CREATE SCHEMA stub."""
        return f'CREATE SCHEMA IF NOT EXISTS {cls.schema};'

    @classmethod
    def _query_create_table(cls) -> str:
        """Generates the CREATE TABLE stub."""
        builder = [f'CREATE TABLE IF NOT EXISTS {cls._name} (']

        primary_keys = []
        for column in cls._columns.values():
            if column.primary_key:
                primary_keys.append(column.name)

            builder.append(f'\t{column},')

        builder.append(f'\tPRIMARY KEY ({", ".join(primary_keys)})')

        builder.append(');')

        return "\n".join(builder)

    @classmethod
    def _query_insert(cls, returning, **kwargs) -> Tuple[str, Iterable]:
        """Generates the INSERT INTO stub."""
        verified = cls._validate_kwargs(**kwargs)

        builder = [f'INSERT INTO {cls._name}']
        builder.append(f'({", ".join(verified)})')
        builder.append('VALUES')

        values = []
        for i, _ in enumerate(verified, 1):
            values.append(f'${i}')
        builder.append(f'({", ".join(values)})')

        if returning:
            builder.append('RETURNING')

            if returning == '*':
                builder.append('*')

            else:

                # Convert to tuple if object is not iter
                if not isinstance(returning, Iterable):
                    returning = (returning,)

                returning_builder = []

                for value in returning:
                    if not isinstance(value, Column):
                        raise TypeError(
                            f'Expected a volume for the returning value recieved {type(value).__name__}')
                    returning_builder.append(value.name)

                builder.append(', '.join(returning_builder))

        return (" ".join(builder), verified.values())

    @classmethod
    def _query_insert_many(cls, columns) -> str:
        """Generates the INSERT INTO stub."""
        builder = [f'INSERT INTO {cls._name}']
        builder.append(f'({", ".join(column.name for column in columns)})')
        builder.append('VALUES')
        builder.append(
            f'({", ".join(f"${n+1}" for n in range(len(columns)))})')

        return " ".join(builder)

    @classmethod
    def _query_fetch(cls, order_by, limit, **kwargs) -> Tuple[str, Iterable]:
        """Generates the SELECT FROM stub"""
        verified = cls._validate_kwargs(**kwargs)

        builder = [f'SELECT * FROM {cls._name}']

        # Set the WHERE clause
        if verified:
            builder.append('WHERE')
            checks = []
            for i, key in enumerate(verified, 1):
                checks.append(f'{key} = ${i}')
            builder.append(' AND '.join(checks))

        if order_by is not None:
            builder.append(f'ORDER BY {order_by}')

        if limit is not None:
            builder.append(f'LIMIT {limit}')

        return (" ".join(builder), verified.values())

    @classmethod
    def _query_fetch_where(cls, query, order_by, limit) -> str:
        """Generates the SELECT FROM stub"""

        builder = [f'SELECT * FROM {cls._name} WHERE']
        builder.append(query)

        if order_by is not None:
            builder.append(f'ORDER BY {order_by}')

        if limit is not None:
            builder.append(f'LIMIT {limit}')

        return " ".join(builder)

    @classmethod
    def _query_update_record(cls, record, **kwargs) -> Tuple[str, List[Any]]:
        '''Generates the UPDATE stub'''
        verified = cls._validate_kwargs(**kwargs)

        builder = [f'UPDATE {cls._name} SET']

        # Set the values
        sets = []
        for i, key in enumerate(verified, 1):
            sets.append(f'{key} = ${i}')
        builder.append(', '.join(sets))

        # Set the QUERY
        record_keys = cls._validate_kwargs(primary_keys_only=True, **record)

        builder.append('WHERE')
        checks = []
        for i, key in enumerate(record_keys, i+1):
            checks.append(f'{key} = ${i}')
        builder.append(' AND '.join(checks))

        return (" ".join(builder), list(verified.values()) + list(record_keys.values()))

    @classmethod
    def _query_update_where(cls, query, values, **kwargs) -> Tuple[str, List[Any]]:
        '''Generates the UPDATE stub'''
        verified = cls._validate_kwargs(**kwargs)

        builder = [f'UPDATE {cls._name} SET']

        # Set the values
        sets = []
        for i, key in enumerate(verified, len(values) + 1):
            sets.append(f'{key} = ${i}')
        builder.append(', '.join(sets))

        # Set the QUERY
        builder.append('WHERE')
        builder.append(query)

        return (" ".join(builder), values + tuple(verified.values()))

    @classmethod
    def _query_delete_record(cls, record) -> Tuple[str, List[Any]]:
        '''Generates the DELETE stub'''

        builder = [f'DELETE FROM {cls._name}']

        # Set the QUERY
        record_keys = cls._validate_kwargs(primary_keys_only=True, **record)

        builder.append('WHERE')
        checks = []
        for i, key in enumerate(record_keys, 1):
            checks.append(f'{key} = ${i}')
        builder.append(' AND '.join(checks))

        return (" ".join(builder), record_keys.values())

    @classmethod
    def _query_delete_where(cls, query) -> str:
        '''Generates the UPDATE stub'''

        builder = [f'DELETE FROM {cls._name}']

        # Set the QUERY
        builder.append('WHERE')
        builder.append(query)

        return " ".join(builder)

    # endregion

    @classmethod
    async def drop_table(cls, connection: asyncpg.Connection = None):
        """Drops this table from the database.

        Args:
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool.
        """
        async with MaybeAcquire(connection) as connection:
            await connection.execute(cls._query_drop_table(True))

    @classmethod
    async def create_table(cls, connection: asyncpg.Connection = None, drop_if_exists: bool = False):
        """Creates this table in the database.

        Args:
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool.
            drop_if_exists (bool, optional): Specified wether the table should be
                first dropped from the database if it already exists.
        """
        async with MaybeAcquire(connection) as connection:
            if drop_if_exists:
                await cls.drop_table(connection)
            await connection.execute(cls._query_create_schema())
            await connection.execute(cls._query_create_table())

    @classmethod
    async def prepare(cls, query: str, connection: asyncpg.Connection = None) -> asyncpg.prepared_stmt.PreparedStatement:
        """Creates a :class:`asyncpg.prepared_stmt.PreparedStatement` based on the given query.

        Args:
            query (str): The SQL query to prepare.
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool.

        Returns:
            asyncpg.prepared_stmt.PreparedStatement: The prepared statement object.
        """
        async with MaybeAcquire(connection) as connection:
            return await connection.prepare(query)

    @classmethod
    async def fetch(cls, connection: asyncpg.Connection = None, order_by: str = None, limit: int = None, **kwargs) -> List[asyncpg.Record]:
        """Fetches a list of records from the database.

        Args:
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool.
            order_by (str, optional): Sets the `ORDER BY` constraint.
            limit (int, optional): Sets the maximum number of records to fetch.
            **kwargs (any): Database :class:`Column` values to search for

        Returns:
            list(asyncpg.Record): A list of database records.
        """
        query, values = cls._query_fetch(order_by, limit, **kwargs)
        async with MaybeAcquire(connection) as connection:
            return await connection.fetch(query, *values)

    @classmethod
    async def fetchall(cls, connection: asyncpg.Connection = None, order_by: str = None, limit: int = None) -> List[asyncpg.Record]:
        """Fetches a list of all records from the database.

        Args:
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool
            order_by (str, optional): Sets the `ORDER BY` constraint
            limit (int, optional): Sets the maximum number of records to fetch

        Returns:
            list(asyncpg.Record): A list of database records.
        """
        query, values = cls._query_fetch(order_by, limit)
        async with MaybeAcquire(connection) as connection:
            return await connection.fetch(query, *values)

    @classmethod
    async def fetch_where(cls, where: str, values: Optional[Tuple[Any]] = tuple(), connection: asyncpg.Connection = None, order_by: str = None, limit: int = None) -> List[asyncpg.Record]:
        """Fetches a list of records from the database.

        Args:
            where (str): An SQL Query to pass
            values (tuple, optional): A tuple containing accomanying values.
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool.
            order_by (str, optional): Sets the `ORDER BY` constraint.
            limit (int, optional): Sets the maximum number of records to fetch.

        Returns:
            list(asyncpg.Record): A list of database records.
        """
        query = cls._query_fetch_where(where, order_by, limit)
        async with MaybeAcquire(connection) as connection:
            return await connection.fetch(query, *values)

    @classmethod
    async def fetchrow(cls, connection: asyncpg.Connection = None, order_by: str = None, **kwargs) -> asyncpg.Record:
        """Fetches a record from the database.

        Args:
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool.
            order_by (str, optional): Sets the `ORDER BY` constraint.
            **kwargs (any): Database :class:`Column` values to search for

        Returns:
            asyncpg.Record: A record from the database.
        """

        query, values = cls._query_fetch(None, None, **kwargs)
        async with MaybeAcquire(connection) as connection:
            return await connection.fetchrow(query, *values)

    @classmethod
    async def fetchrow_where(cls, where: str, values: Optional[Tuple[Any]] = tuple(), connection: asyncpg.Connection = None, order_by: str = None) -> List[asyncpg.Record]:
        """Fetches a record from the database.

        Args:
            where (str): An SQL Query to pass
            values (tuple, optional): A tuple containing accomanying values.
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool.
            order_by (str, optional): Sets the `ORDER BY` constraint.

        Returns:
            asyncpg.Record: A record from the database.
        """
        query = cls._query_fetch_where(where, order_by, None)
        async with MaybeAcquire(connection) as connection:
            return await connection.fetchrow(query, *values)

    @classmethod
    async def insert(cls, connection: asyncpg.Connection = None, returning: Iterable[Column] = None, **kwargs) -> Optional[asyncpg.Record]:
        """Inserts a new record into the database.

        Args:
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool.
            returning (list(Column), optional): A list of columns from this record to return
            **kwargs (any): The records column values.

        Returns:
            (asyncpy.Record, optional): The record inserted into the database
        """
        query, values = cls._query_insert(returning, **kwargs)
        async with MaybeAcquire(connection) as connection:
            if returning:
                return await connection.fetchrow(query, *values)
            await connection.execute(query, *values)

    @classmethod
    async def insert_many(cls, columns: Iterable[Column], values: Iterable[Iterable[Any]], connection: asyncpg.Connection = None):
        """Inserts multiple records into the database.

        Args:
            columns (list(Column)): The list of columns to insert based on.
            values (list(list)): The list of values to insert into the database. 

            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool.
        """
        query = cls._query_insert_many(columns)

        async with MaybeAcquire(connection) as connection:
            await connection.executemany(query, values)

    @classmethod
    async def update_record(cls, record: asyncpg.Record, connection: asyncpg.Connection = None, **kwargs):
        """Updates a record in the database.

        Args:	
            record (asyncpg.Record): The database record to update
            connection (asyncpg.Connection, optional): A database connection to use.	
                If none is supplied a connection will be acquired from the pool	
            **kwargs: Values to update	
        """
        query, values = cls._query_update_record(record, **kwargs)
        async with MaybeAcquire(connection) as connection:
            await connection.execute(query, *values)

    @classmethod
    async def update_where(cls, where: str, values: Optional[Tuple[Any]] = tuple(), connection: asyncpg.Connection = None, **kwargs):
        """Updates any record in the database which satisfies the query.

        Args:	
            where (str): An SQL Query to pass
            values (tuple, optional): A tuple containing accomanying values.
            connection (asyncpg.Connection, optional): A database connection to use.	
                If none is supplied a connection will be acquired from the pool	
            **kwargs: Values to update	
        """

        query, values = cls._query_update_where(where, values, **kwargs)
        async with MaybeAcquire(connection) as connection:
            await connection.execute(query, *values)

    @classmethod
    async def delete_record(cls, record: asyncpg.Record, connection: asyncpg.Connection = None):
        """Deletes a record in the database.

        Args:
            record (asyncpg.Record): The database record to delete
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool

        """
        query, values = cls._query_delete_record(record)
        async with MaybeAcquire(connection) as connection:
            await connection.execute(query, *values)

    @classmethod
    async def delete_where(cls, where: str, values: Optional[Tuple[Any]] = tuple(), connection: asyncpg.Connection = None):
        """Deletes any record in the database which statisfies the query.

        Args:
            where (str): An SQL Query to pass
            values (tuple, optional): A tuple containing accomanying values.
            connection (asyncpg.Connection, optional): A database connection to use.
                If none is supplied a connection will be acquired from the pool

        """
        query = cls._query_delete_where(where)
        async with MaybeAcquire(connection) as connection:
            await connection.execute(query, *values)


async def create_tables(connection: asyncpg.Connection = None, drop_if_exists: bool = False):
    """Create all defined tables.

    Args:
        connection (asyncpg.Connection, optional): A database connection to use.
            If none is supplied a connection will be acquired from the pool.
        drop_if_exists (bool, optional): Specifies wether the table should be
                first dropped from the database if it already exists.
    """
    async with MaybeAcquire(connection=connection) as connection:
        for table in Table.__subclasses__():
            await table.create_table(connection=connection, drop_if_exists=drop_if_exists)
