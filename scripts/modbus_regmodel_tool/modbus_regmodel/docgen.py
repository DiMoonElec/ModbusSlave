"""Генерация markdown-документации по регистровой карте.

Документ состоит из трёх частей:

1. Статическое введение о том, как типы данных ложатся на Modbus-регистры
   (holding-регистры, разрядность, атомарность 32-битных значений, bool).
2. Человекочитаемое описание регистров "как они заданы в YAML" (без развёртки
   count/repeat в отдельные строки на каждый экземпляр) - обычные регистры и
   блоки отдельно, без getter/setter.
3. Плоская таблица адресов: dec -> hex -> итоговое сгенерированное имя,
   по одной строке на каждый реально занятый Modbus-адрес.
"""
from __future__ import annotations

from .model import FlatRegister, LogicalBlock, LogicalTopRegister, ParseResult

INTRO = """\
## 1. Регистры Modbus

Все регистры, перечисленные в этом документе, - Modbus **holding-регистры**.
Один Modbus-регистр имеет ширину 16 бит.

Соответствие типов данных и занимаемых Modbus-регистров:

| Тип данных                          | Регистров занимает | Примечание |
| ------------------------------------ | :-----------------: | ---------- |
| `bool`                                | 1                    | `0` - `false`, любое отличное от нуля значение - `true` |
| `uint8_t` / `int8_t`                  | 1                    | |
| `uint16_t` / `int16_t`                | 1                    | |
| `uint32_t` / `int32_t` / `float`      | 2                    | занимают два **соседних** регистра: `addr` и `addr + 1` |

**Важно про 32-битные значения (`uint32_t`, `int32_t`, `float`).** Такое
значение физически лежит в двух соседних регистрах. Читать и писать его нужно
**одним запросом** к обоим регистрам сразу (а не двумя отдельными запросами
по одному регистру). При записи это дополнительно даёт атомарность: новое
значение применяется, только если обе половинки пришли в одном запросе -
частично записанное (только одна половина) значение не подставляется.

Адреса в этом документе - это адреса Modbus-регистров (register address), а
не байтовые смещения. Как именно мастер интерпретирует эти адреса (0-based
или 1-based, конкретные коды функций чтения/записи) - зависит от используемой
реализации мастера/SCADA и здесь не оговаривается.
"""


def _addr_dec_hex(addr: int) -> str:
    return f"{addr} (0x{addr:04X})"


def _addr_range_dec_hex(addr_from: int, addr_to: int) -> str:
    if addr_from == addr_to:
        return _addr_dec_hex(addr_from)
    return f"{addr_from} .. {addr_to} (0x{addr_from:04X} .. 0x{addr_to:04X})"


def _val_or_dash(value) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def _render_top_registers(top_registers: list[LogicalTopRegister]) -> list[str]:
    lines: list[str] = []
    lines.append("## 2. Обычные регистры\n")

    if not top_registers:
        lines.append("_В этом файле нет регистров верхнего уровня (`registers`)._\n")
        return lines

    lines.append("| Имя | Адрес | Тип | Доступ | Кол-во элементов | Описание | Ед. изм. |")
    lines.append("| --- | --- | --- | --- | :---: | --- | :---: |")

    for reg in sorted(top_registers, key=lambda r: r.addr):
        name = reg.name or "_(без имени)_"
        addr_str = _addr_range_dec_hex(reg.addr, reg.end_addr)
        row = [
            name,
            addr_str,
            reg.canonical_type,
            reg.access_mode,
            str(reg.count) if reg.count is not None else "—",
            _val_or_dash(reg.description),
            _val_or_dash(reg.unit),
        ]
        lines.append("| " + " | ".join(_md_escape(c) for c in row) + " |")

    lines.append("")
    return lines


def _render_blocks(blocks: list[LogicalBlock]) -> list[str]:
    lines: list[str] = []
    lines.append("## 3. Блоки регистров\n")

    if not blocks:
        lines.append("_В этом файле нет блоков (`blocks`)._\n")
        return lines

    lines.append(
        "Блок - это повторяющаяся группа регистров (например, один блок на "
        "каждый из нескольких однотипных каналов/устройств). Ниже для каждого "
        "блока сначала указаны его общие параметры (адрес первого экземпляра, "
        "количество экземпляров, шаг между ними), а затем - регистры **внутри "
        "одного экземпляра** со смещением относительно начала экземпляра.\n"
    )

    for block in sorted(blocks, key=lambda b: b.start_addr):
        last_start = block.start_addr + (block.repeat - 1) * block.step
        lines.append(f"### Блок `{block.name}`\n")
        lines.append(f"- Адрес первого экземпляра: {_addr_dec_hex(block.start_addr)}")
        lines.append(f"- Адрес последнего экземпляра: {_addr_dec_hex(last_start)}")
        lines.append(f"- Количество экземпляров: {block.repeat}")
        lines.append(f"- Шаг между экземплярами: {block.step} (0x{block.step:02X}) регистров")
        lines.append("")

        lines.append("| Имя (внутри экземпляра) | Смещение | Тип | Доступ | Кол-во элементов | Описание | Ед. изм. |")
        lines.append("| --- | --- | --- | --- | :---: | --- | :---: |")
        for reg in sorted(block.registers, key=lambda r: r.offset):
            name = reg.name or "_(без имени)_"
            if reg.offset == reg.end_offset:
                offset_str = f"{reg.offset} (0x{reg.offset:02X})"
            else:
                offset_str = f"{reg.offset} .. {reg.end_offset} (0x{reg.offset:02X} .. 0x{reg.end_offset:02X})"
            row = [
                name,
                offset_str,
                reg.canonical_type,
                reg.access_mode,
                str(reg.count) if reg.count is not None else "—",
                _val_or_dash(reg.description),
                _val_or_dash(reg.unit),
            ]
            lines.append("| " + " | ".join(_md_escape(c) for c in row) + " |")
        lines.append("")

    return lines


def _render_flat_table(registers: list[FlatRegister]) -> list[str]:
    lines: list[str] = []
    lines.append("## 4. Плоская модель (полная карта адресов)\n")
    lines.append(
        "Полный список фактически занятых Modbus-адресов после развёртки всех "
        "`count` и `blocks` в отдельные регистры, с точными именами, которые "
        "использует сгенерированный C-код (`#define`). Адреса, не попавшие в "
        "этот список, не заняты ни одним регистром. Для значений, занимающих "
        "2 регистра (`uint32_t`/`int32_t`/`float`), в столбцах адреса указан "
        "диапазон обоих регистров - обращаться к ним нужно одним запросом "
        "(см. раздел 1).\n"
    )
    lines.append("| Адрес (dec) | Адрес (hex) | Имя | Тип | Доступ |")
    lines.append("| ---: | :---: | --- | --- | :---: |")

    for reg in sorted(registers, key=lambda r: r.addr):
        name = reg.c_name or "—"
        if reg.addr == reg.end_addr:
            dec_str = str(reg.addr)
            hex_str = f"0x{reg.addr:04X}"
        else:
            dec_str = f"{reg.addr} .. {reg.end_addr}"
            hex_str = f"0x{reg.addr:04X} .. 0x{reg.end_addr:04X}"
        lines.append(
            f"| {dec_str} | {hex_str} | {_md_escape(name)} | "
            f"{reg.canonical_type} | {reg.access_mode} |"
        )

    lines.append("")
    return lines


def generate_markdown(result: ParseResult) -> str:
    """Собирает полный markdown-документ по уже провалидированной модели.

    Вызывающая сторона должна убедиться, что result.errors пуст и
    validate.validate_model(result.registers) не вернула ошибок - документ
    генерируется на тех же данных, что и C-код, и рассчитан на то, что модель
    непротиворечива."""
    parts: list[str] = []
    parts.append("# Регистровая карта устройства (Modbus)\n")
    parts.append(INTRO)
    parts.extend(_render_top_registers(result.top_registers))
    parts.extend(_render_blocks(result.blocks))
    parts.extend(_render_flat_table(result.registers))
    return "\n".join(parts).rstrip() + "\n"
