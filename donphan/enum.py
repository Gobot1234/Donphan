from abc import ABCMeta
import enum
from functools import total_ordering

from .abc import Creatable


class EnumMeta(ABCMeta, enum.EnumMeta):
    pass


@total_ordering
class Enum(Creatable, str, enum.Enum, metaclass=EnumMeta):
    @classmethod
    def _query_drop(cls, if_exists: bool = True, cascade: bool = False) -> str:
        raise NotImplementedError('Enums cannot be dropped')

    @classmethod
    def _query_create(cls, drop_if_exists: bool = True, if_not_exists: bool = True) -> str:
        builder = ["CREATE TYPE"]
        builder.append(f"{cls.__name__} as ENUM {tuple(cls._member_map_)};")
        return " ".join(builder)

    def __lt__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        member_names = tuple(self._member_map_)
        return member_names.index(self.name) < member_names.index(other.name)
