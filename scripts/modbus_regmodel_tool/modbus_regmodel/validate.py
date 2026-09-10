"""Перекрёстные проверки плоской регистровой модели.

В отличие от model.parse_spec (структурный разбор одного элемента YAML),
проверки здесь требуют видеть модель целиком: уникальность итоговых
C-имён и отсутствие пересечений адресов между произвольными записями.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .model import FlatRegister


def validate_model(registers: Iterable[FlatRegister]) -> list[str]:
    """Возвращает список всех найденных ошибок, не останавливаясь на первой."""
    registers = list(registers)
    errors: list[str] = []
    errors.extend(_check_unique_names(registers))
    errors.extend(_check_overlaps(registers))
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


def _check_overlaps(registers: list[FlatRegister]) -> list[str]:
    """
    Проверка пересечений диапазонов адресов.

    Реализована как sweep по левой границе с отслеживанием максимального
    встреченного правого края, а не сравнением только соседних пар после
    сортировки по адресу. Сравнение только соседних пар корректно лишь пока
    ни одна запись не занимает больше 2 регистров (иначе один широкий
    интервал может "перепрыгнуть" через дыру и пропустить пересечение с
    записью через один шаг). Sweep с максимумом корректен всегда, независимо
    от ширины записей - это важно, если формат когда-нибудь получит более
    широкие типы (например, 64-битные).
    """
    errors: list[str] = []
    ordered = sorted(registers, key=lambda r: (r.addr, r.end_addr))

    max_end = -1
    max_end_owner: Optional[FlatRegister] = None

    for reg in ordered:
        if max_end_owner is not None and reg.addr <= max_end:
            errors.append(
                f"Пересечение адресов: '{max_end_owner.id}' "
                f"(0x{max_end_owner.addr:04X}..0x{max_end_owner.end_addr:04X}) "
                f"и '{reg.id}' (0x{reg.addr:04X}..0x{reg.end_addr:04X})"
            )
        if reg.end_addr > max_end:
            max_end = reg.end_addr
            max_end_owner = reg

    return errors
