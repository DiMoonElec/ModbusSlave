"""Общие типы, константы и вспомогательные структуры данных генератора."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# --- Нормализация типов из YAML в canonical-тип -----------------------------

TYPE_ALIASES: dict[str, str] = {
    'bool': 'bool', 'boolean': 'bool',
    'uint8_t': 'uint8_t', 'uint8': 'uint8_t', 'uchar': 'uint8_t', 'byte': 'uint8_t',
    'int8_t': 'int8_t', 'int8': 'int8_t', 'char': 'int8_t', 'sbyte': 'int8_t',
    'uint16_t': 'uint16_t', 'uint16': 'uint16_t', 'ushort': 'uint16_t',
    'int16_t': 'int16_t', 'int16': 'int16_t', 'short': 'int16_t',
    'uint32_t': 'uint32_t', 'uint32': 'uint32_t', 'uint': 'uint32_t',
    'int32_t': 'int32_t', 'int32': 'int32_t', 'int': 'int32_t',
    'float': 'float',
}

CANONICAL_TYPES = frozenset(TYPE_ALIASES.values())

# Сколько 16-битных Modbus-регистров занимает один элемент значения данного типа.
REGS_PER_TYPE: dict[str, int] = {
    'bool': 1, 'uint8_t': 1, 'int8_t': 1,
    'uint16_t': 1, 'int16_t': 1,
    'uint32_t': 2, 'int32_t': 2, 'float': 2,
}

# Каким по разрядности вызовом библиотеки (modbus_slave_*_holding_regN) нужно
# пользоваться для данного canonical-типа.
#
# ВНИМАНИЕ: для bool это 16, хотя физически регистр всего один (см. REGS_PER_TYPE) -
# на границе с библиотекой bool всегда передаётся как 16-битное значение (0 / не-0).
# Именно рассинхрон этих двух таблиц был источником одного из багов в предыдущей
# версии генератора, поэтому они сознательно разведены и не переиспользуют друг друга.
REG_SIZE_FOR_TYPE: dict[str, int] = {
    'bool': 16,
    'uint8_t': 8, 'int8_t': 8,
    'uint16_t': 16, 'int16_t': 16,
    'uint32_t': 32, 'int32_t': 32,
    'float': 32,
}

# Короткое имя типа - используется только для составления читаемых имён
# generated-функций (не участвует в кодогенерации логики).
TYPE_SHORT_NAME: dict[str, str] = {
    'bool': 'bool',
    'uint8_t': 'u8', 'int8_t': 's8',
    'uint16_t': 'u16', 'int16_t': 's16',
    'uint32_t': 'u32', 'int32_t': 's32',
    'float': 'f32',
}


def normalize_type(raw: object) -> Optional[str]:
    """Возвращает canonical-тип по значению из YAML, либо None если тип неизвестен."""
    if not isinstance(raw, str):
        return None
    return TYPE_ALIASES.get(raw.strip().lower())


# --- Форма сигнатуры getter/setter ------------------------------------------
#
# 'scalar'    -> T getter(void)                              / void setter(T)
# 'idx'       -> T getter(uint16_t index)                    / void setter(uint16_t index, T)
# 'inst'      -> T getter(uint16_t instance)                 / void setter(uint16_t instance, T)
# 'inst_elem' -> T getter(uint16_t instance, uint16_t elem)  / void setter(uint16_t instance, uint16_t elem, T)

INDEXING_SCALAR = 'scalar'
INDEXING_IDX = 'idx'
INDEXING_INST = 'inst'
INDEXING_INST_ELEM = 'inst_elem'

VALID_INDEXINGS = (INDEXING_SCALAR, INDEXING_IDX, INDEXING_INST, INDEXING_INST_ELEM)


@dataclass(frozen=True)
class WrapperKey:
    """
    Однозначно описывает одну helper-обёртку конвертации между представлением
    Modbus-регистра (1/2 регистра нужной разрядности) и типизированным
    getter/setter пользовательского кода.

    В отличие от подхода "закодировать всё в строку имени функции, а потом
    распарсить её обратно", имя обёртки (.name) всегда ВЫВОДИТСЯ из полей этой
    структуры, а не наоборот. Это устраняет целый класс ошибок рассинхронизации
    между кодированием и декодированием (именно так в первой версии генератора
    появился баг с использованием reg16 вместо reg8 для 8-битных типов).
    """
    operation: str          # 'read' или 'write'
    canonical_type: str     # 'bool', 'uint8_t', 'int8_t', ..., 'float'
    indexing: str           # одно из VALID_INDEXINGS

    def __post_init__(self) -> None:
        if self.operation not in ('read', 'write'):
            raise ValueError(f"Недопустимая операция обёртки: {self.operation!r}")
        if self.canonical_type not in CANONICAL_TYPES:
            raise ValueError(f"Недопустимый canonical-тип: {self.canonical_type!r}")
        if self.indexing not in VALID_INDEXINGS:
            raise ValueError(f"Недопустимая форма индексации: {self.indexing!r}")

    @property
    def reg_size(self) -> int:
        return REG_SIZE_FOR_TYPE[self.canonical_type]

    @property
    def lib_func(self) -> str:
        return f"modbus_slave_{self.operation}_holding_reg{self.reg_size}"

    @property
    def name(self) -> str:
        suffix = '' if self.indexing == INDEXING_SCALAR else f'_{self.indexing}'
        short = TYPE_SHORT_NAME[self.canonical_type]
        return f"{self.operation}_reg{self.reg_size}_{short}{suffix}"
