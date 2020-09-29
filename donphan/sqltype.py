import datetime
import decimal
import ipaddress
import uuid
from typing import Callable, Dict, Generic, Type, TypeVar
from typing_extensions import Literal

from .enum import Enum

PY_T = TypeVar("PY_T", bound=type)
SQL_T = TypeVar("SQL_T", bound=str)
SQLTypeClassMethod = Callable[[Type['SQLType']], 'SQLType']
_defaults: Dict[PY_T, SQLTypeClassMethod] = {}


def default_for(python_type: PY_T) -> Callable[[SQLTypeClassMethod], SQLTypeClassMethod]:
    """Sets a specified python type's default SQL type.
    Args:
        python_type (type): Python type to set the specified sqltype as default for.
    """
    def func(sql_type: SQLTypeClassMethod) -> SQLTypeClassMethod:
        _defaults[python_type] = sql_type
        return sql_type
    return func


class SQLType(Generic[PY_T, SQL_T]):
    python = NotImplemented
    sql = NotImplemented

    def __init__(self, python: PY_T, sql: SQL_T):
        self.python = python
        self.sql = sql

    def __repr__(self) -> str:
        return f'<SQLType sql={self.sql!r} python={self.__name__!r}>'

    def __eq__(self, other) -> bool:
        return isinstance(other, self.__class__) and self.sql == other.sql

    @property
    def __name__(self) -> str:
        return self.python.__name__

    # 8.1 Numeric

    @classmethod
    @default_for(int)
    def Integer(cls) -> 'SQLType[int, Literal["INTEGER"]]':
        """Postgres Integer Type"""
        return cls(int, 'INTEGER')

    @classmethod
    def SmallInt(cls) -> 'SQLType[int, Literal["SMALLINT"]]':
        """Postgres SmallInt Type"""
        return cls(int, 'SMALLINT')

    @classmethod
    def BigInt(cls) -> 'SQLType[int, Literal["BIGINT"]]':
        """Postgres BigInt Type"""
        return cls(int, 'BIGINT')

    @classmethod
    def Serial(cls) -> 'SQLType[int, Literal["SERIAL"]]':
        """Postgres Serial Type"""
        return cls(int, 'SERIAL')

    @classmethod
    @default_for(float)
    def Float(cls) -> 'SQLType[float, Literal["FLOAT"]]':
        """Postgres Float Type"""
        return cls(float, 'FLOAT')

    @classmethod
    def DoublePrecision(cls) -> 'SQLType[float, Literal["DOUBLE PRECISION"]]':
        """Postgres DoublePrecision Type"""
        return cls(float, 'DOUBLE PRECISION')

    @classmethod
    @default_for(decimal.Decimal)
    def Numeric(cls) -> 'SQLType[decimal.Decimal, Literal["NUMERIC"]]':
        """Postgres Numeric Type"""
        return cls(decimal.Decimal, 'NUMERIC')

    # 8.2 Monetary

    @classmethod
    def Money(cls) -> 'SQLType[str, Literal["MONEY"]]':
        """Postgres Money Type"""
        return cls(str, 'MONEY')

    # 8.3 Character

    @classmethod
    def CharacterVarying(cls, n: int = 2000) -> 'SQLType[str, str]':
        return cls(str, f'CHARACTER VARYING({n})')

    @classmethod
    def Character(cls) -> 'SQLType[str, Literal["CHARACTER"]]':
        """Postgres Character Type"""
        return cls(str, 'CHARACTER')

    @classmethod
    @default_for(str)
    def Text(cls) -> 'SQLType[str, Literal["TEXT"]]':
        """Postgres Text Type"""
        return cls(str, 'TEXT')

    # 8.4 Binary

    @classmethod
    @default_for(bytes)
    def Bytea(cls) -> 'SQLType[bytes, Literal["BYTEA"]]':
        """Postgres Bytea Type"""
        return cls(bytes, 'BYTEA')

    # 8.5 Date/Time

    @classmethod
    @default_for(datetime.datetime)
    def Timestamp(cls) -> 'SQLType[datetime.datetime, Literal["TIMESTAMP"]]':
        """Postgres Timestamp Type"""
        return cls(datetime.datetime, 'TIMESTAMP')

    @classmethod
    @default_for(datetime.date)
    def Date(cls) -> 'SQLType[datetime.date, Literal["DATE"]]':
        """Postgres Date Type"""
        return cls(datetime.date, 'DATE')

    @classmethod
    @default_for(datetime.timedelta)
    def Interval(cls) -> 'SQLType[datetime.timedelta, Literal["INTERVAL"]]':
        """Postgres Interval Type"""
        return cls(datetime.timedelta, 'INTERVAL')

    # 8.6 Boolean

    @classmethod
    @default_for(bool)
    def Boolean(cls) -> 'SQLType[bool, Literal["BOOLEAN"]]':
        """Postgres Boolean Type"""
        return cls(bool, 'BOOLEAN')

    # 8.7 Enum

    @classmethod
    @default_for(Enum)
    def Enum(cls) -> 'SQLType[Enum, Literal["ENUM"]]':
        """Postgres Enum Type"""
        return cls(Enum, 'ENUM')

    # 8.9 Network Adress

    @classmethod
    @default_for(ipaddress.IPv4Network)
    @default_for(ipaddress.IPv6Network)
    def CIDR(cls) -> 'SQLType[ipaddress._BaseNetwork, Literal["CIDR"]]':
        """Postgres CIDR Type"""
        return cls(ipaddress._BaseNetwork, 'CIDR')

    @classmethod
    @default_for(ipaddress.IPv4Address)
    @default_for(ipaddress.IPv6Address)
    def Inet(cls) -> 'SQLType[CIDR, Literal["INET"]]':
        """Postgres Inet Type"""
        return cls(ipaddress._BaseNetwork, 'INET')

    @classmethod
    def MACAddr(cls) -> 'SQLType[str, Literal["MACADDR"]]':
        """Postgres MACAddr Type"""
        return cls(str, 'MACADDR')

    # 8.12 UUID

    @classmethod
    @default_for(uuid.UUID)
    def UUID(cls) -> 'SQLType[uuid.UUID, Literal["UUID"]]':
        """Postgres UUID Type"""
        return cls(uuid.UUID, 'UUID')

    # 8.14 JSON

    @classmethod
    def JSON(cls) -> 'SQLType[dict, Literal["JSON"]]':
        """Postgres JSON Type"""
        return cls(dict, 'JSON')

    @classmethod
    @default_for(dict)
    def JSONB(cls) -> 'SQLType[dict, Literal["JSONB"]]':
        """Postgres JSONB Type"""
        return cls(dict, 'JSONB')

    # Aliases
    Char = Character
    VarChar = CharacterVarying

    @classmethod
    def _from_python_type(cls, python_type: PY_T) -> SQL_T:
        """Dynamically determines an SQL type given a python type.
        Args:
            python_type (type): The python type.
        """

        try:
            return _defaults[python_type](cls)
        except KeyError:
            raise TypeError(
                f'Could not find an applicable SQL type for Python type {python_type.__name__}.') from None
