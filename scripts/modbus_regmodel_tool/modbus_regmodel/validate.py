"""Перекрёстные проверки плоской регистровой модели.

В отличие от model.parse_spec (структурный разбор одного элемента YAML),
проверки здесь требуют видеть модель целиком: уникальность итоговых
C-имён и отсутствие пересечений адресов между произвольными записями.
"""
from __future__ import annotations

from typing import Iterable

from .model import FlatRegister, LogicalBlock


def validate_model(registers: Iterable[FlatRegister], blocks: Iterable[LogicalBlock]) -> list[str]:
    """Возвращает список всех найденных ошибок, не останавливаясь на первой."""
    registers = list(registers)
    errors: list[str] = []
    errors.extend(_check_unique_names(registers))
    errors.extend(_check_overlaps(registers, blocks))
    return errors


def _check_unique_names(registers: list[FlatRegister]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for reg in registers:
        name = reg.c_name
        if name is None:
            continue
        if name in seen:
            errors.append(f"Дублирование сгенерированного имени '{name}': {reg.id} и {seen[name]}")
        else:
            seen[name] = reg.id
    return errors


def _check_overlaps(registers: list[FlatRegister], blocks: Iterable[LogicalBlock]) -> list[str]:
    """
    Проверка пересечений диапазонов адресов.

    Каждый блок занимает всю область до end_addr, включая хвост последнего
    экземпляра или колонки. Его поля уже размещены парсером, поэтому
    проверяются области блоков и регистры верхнего уровня. Максимум правого
    края позволяет обнаружить и вложенные пересечения.
    """
    errors: list[str] = []
    regions = [(r.addr, r.end_addr, r.id) for r in registers if not r.is_in_block]
    regions.extend((b.start_addr, b.end_addr, f"block '{b.name}'") for b in blocks)

    max_end = -1
    max_owner = None

    for start, end, owner in sorted(regions):
        if max_owner is not None and start <= max_end:
            errors.append(
                f"Пересечение адресов: '{max_owner[2]}' "
                f"(0x{max_owner[0]:04X}..0x{max_end:04X}) "
                f"и '{owner}' (0x{start:04X}..0x{end:04X})"
            )
        if end > max_end:
            max_end = end
            max_owner = (start, end, owner)

    return errors
