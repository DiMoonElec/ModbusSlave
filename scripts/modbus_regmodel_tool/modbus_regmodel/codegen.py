"""Генерация содержимого .h и .c файлов из плоской регистровой модели."""
from __future__ import annotations

from .model import FlatRegister
from .types import WrapperKey, INDEXING_SCALAR, INDEXING_IDX, INDEXING_INST, INDEXING_INST_ELEM

HEADER_TEMPLATE = """\
#ifndef __MODBUS_REG_MODEL_H__
#define __MODBUS_REG_MODEL_H__

#include <stdint.h>

void ModbusRegModelInit(void);

#endif /* __MODBUS_REG_MODEL_H__ */
"""


def generate_header() -> str:
    """Статическое содержимое .h файла.

    Содержимое не зависит от YAML, но всё равно генерируется инструментом
    (а не создаётся один раз вручную), чтобы .h тоже оставался воспроизводимым
    артефактом наравне с .c - единственным исключением из общего правила
    "не редактировать сгенерированное вручную" иначе не должно быть.
    """
    return HEADER_TEMPLATE


# --- Обёртки-конвертеры между Modbus-регистром и типизированным getter/setter --

def _index_param_types(key: WrapperKey) -> list[str]:
    """Голые типы (без имён параметров) - для типа указателя на функцию."""
    if key.indexing == INDEXING_SCALAR:
        return []
    if key.indexing == INDEXING_IDX:
        return ["uint16_t"]
    if key.indexing == INDEXING_INST:
        return ["uint16_t"]
    return ["uint16_t", "uint16_t"]


def _index_param_decls(key: WrapperKey) -> list[str]:
    """Именованные параметры - для собственной сигнатуры обёртки."""
    if key.indexing == INDEXING_SCALAR:
        return []
    if key.indexing == INDEXING_IDX:
        return ["uint16_t idx"]
    if key.indexing == INDEXING_INST:
        return ["uint16_t inst"]
    return ["uint16_t inst", "uint16_t elem"]


def _index_call_args(key: WrapperKey) -> list[str]:
    if key.indexing == INDEXING_SCALAR:
        return []
    if key.indexing == INDEXING_IDX:
        return ["idx"]
    if key.indexing == INDEXING_INST:
        return ["inst"]
    return ["inst", "elem"]


def _render_read_wrapper(key: WrapperKey) -> list[str]:
    c_type = key.canonical_type
    fn_ptr_params = ", ".join(_index_param_types(key)) or "void"
    own_params = ", ".join(
        ["modbus_slave_context_t *ctx", f"{c_type} (*getter)({fn_ptr_params})"] + _index_param_decls(key)
    )
    call_args = ", ".join(_index_call_args(key))

    lines = [f"static void {key.name}({own_params})", "{"]
    if c_type == "bool":
        lines.append(f"    bool val = getter({call_args});")
        lines.append(f"    uint{key.reg_size}_t raw = val ? 1U : 0U;")
        lines.append(f"    {key.lib_func}(ctx, &raw);")
    elif c_type == "float":
        lines.append(f"    float val = getter({call_args});")
        lines.append("    uint32_t raw;")
        lines.append("    memcpy(&raw, &val, sizeof(val));")
        lines.append(f"    {key.lib_func}(ctx, &raw);")
    else:
        lines.append(f"    {c_type} val = getter({call_args});")
        lines.append(f"    {key.lib_func}(ctx, &val);")
    lines.append("}")
    return lines


def _render_write_wrapper(key: WrapperKey) -> list[str]:
    c_type = key.canonical_type
    fn_ptr_params = ", ".join(_index_param_types(key) + [c_type])
    own_params = ", ".join(
        ["modbus_slave_context_t *ctx", f"void (*setter)({fn_ptr_params})"] + _index_param_decls(key)
    )
    call_args = _index_call_args(key)

    lines = [f"static void {key.name}({own_params})", "{"]
    if c_type == "bool":
        lines.append(f"    uint{key.reg_size}_t raw;")
        lines.append(f"    if ({key.lib_func}(ctx, &raw))")
        lines.append("    {")
        lines.append(f"        setter({', '.join(call_args + ['(bool)(raw != 0)'])});")
        lines.append("    }")
    elif c_type == "float":
        lines.append("    uint32_t raw;")
        lines.append(f"    if ({key.lib_func}(ctx, &raw))")
        lines.append("    {")
        lines.append(f"        {c_type} val;")
        lines.append("        memcpy(&val, &raw, sizeof(val));")
        lines.append(f"        setter({', '.join(call_args + ['val'])});")
        lines.append("    }")
    else:
        lines.append(f"    {c_type} val;")
        lines.append(f"    if ({key.lib_func}(ctx, &val))")
        lines.append("    {")
        lines.append(f"        setter({', '.join(call_args + ['val'])});")
        lines.append("    }")
    lines.append("}")
    return lines


def render_wrapper(key: WrapperKey) -> list[str]:
    return _render_read_wrapper(key) if key.operation == "read" else _render_write_wrapper(key)


# --- case-метки диспетчеров -------------------------------------------------

def _case_comment(operation: str, reg: FlatRegister) -> str:
    func_type = "getter" if operation == "read" else "setter"
    func_name = reg.getter if operation == "read" else reg.setter
    parts = [reg.canonical_type, reg.access_mode, f"{func_type}: {func_name}"]
    if reg.is_in_block:
        parts.append(f"inst[{reg.instance_index}]")
    if reg.is_array_element:
        parts.append(f"elem[{reg.elem_index}]")
    return ", ".join(parts)


def _render_case(operation: str, reg: FlatRegister) -> str:
    label = reg.c_name or f"0x{reg.addr:04X}"
    func_name = reg.getter if operation == "read" else reg.setter
    key = WrapperKey(operation=operation, canonical_type=reg.canonical_type, indexing=reg.indexing)
    call_args = ", ".join(["context", func_name] + [str(i) for i in reg.call_index_args])
    comment = _case_comment(operation, reg)
    return (
        f"        case {label}:  /* {comment} */\n"
        f"        {{\n"
        f"            {key.name}({call_args});\n"
        f"        }}\n"
        f"        break;"
    )


# --- Сборка .c файла целиком --------------------------------------------

def generate_source(registers: list[FlatRegister], includes: list[str]) -> str:
    """Регистры должны быть предварительно отсортированы по адресу вызывающей
    стороной (это определяет порядок #define и порядок case в switch)."""
    lines: list[str] = []

    lines.append("/* Файл сгенерирован автоматически. Не редактировать вручную. */")
    lines.append("")
    lines.append("/* === System includes === */")
    lines.append('#include "modbus_reg_model.h"')
    lines.append('#include "ModbusSlave/public-api.h"')
    lines.append("#include <stdint.h>")
    lines.append("#include <stdbool.h>")
    lines.append("#include <string.h>")
    lines.append("")

    if includes:
        lines.append("/* === User includes (из 'includes' в YAML) === */")
        for inc in dict.fromkeys(includes):  # де-дуп, сохраняя порядок
            lines.append(f'#include "{inc}"')
        lines.append("")

    named = [r for r in registers if r.c_name is not None]
    if named:
        lines.append("/* === Symbolic addresses === */")
        width = max(len(r.c_name) for r in named)
        for reg in named:
            lines.append(f"#define {reg.c_name:<{width}} 0x{reg.addr:04X}U")
        lines.append("")

    used_wrappers: "dict[WrapperKey, None]" = {}
    for reg in registers:
        if reg.getter:
            used_wrappers[WrapperKey("read", reg.canonical_type, reg.indexing)] = None
        if reg.setter:
            used_wrappers[WrapperKey("write", reg.canonical_type, reg.indexing)] = None

    if used_wrappers:
        lines.append("/* === Helper wrappers (генерируются только реально используемые) === */")
        lines.append("")
        for key in sorted(used_wrappers, key=lambda k: k.name):
            lines.extend(render_wrapper(key))
            lines.append("")

    lines.append("/* === Read dispatcher === */")
    lines.append("static void RegModelReadHoldingReg(uint16_t reg, modbus_slave_context_t *context)")
    lines.append("{")
    lines.append("    switch (reg)")
    lines.append("    {")
    for reg in registers:
        if reg.getter:
            lines.append(_render_case("read", reg))
    lines.append("    }")
    lines.append("}")
    lines.append("")

    lines.append("/* === Write dispatcher === */")
    lines.append("static void RegModelWriteHoldingReg(uint16_t reg, modbus_slave_context_t *context)")
    lines.append("{")
    lines.append("    switch (reg)")
    lines.append("    {")
    for reg in registers:
        if reg.setter:
            lines.append(_render_case("write", reg))
    lines.append("    }")
    lines.append("}")
    lines.append("")

    lines.append("/* === Init === */")
    lines.append("void ModbusRegModelInit(void)")
    lines.append("{")
    lines.append("    modbus_slave_set_write_holding_reg_callback(RegModelWriteHoldingReg);")
    lines.append("    modbus_slave_set_read_holding_reg_callback(RegModelReadHoldingReg);")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)
