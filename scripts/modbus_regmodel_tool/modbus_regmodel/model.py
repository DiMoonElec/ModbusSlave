"""Разбор YAML-спецификации регистровой карты и построение моделей.

Этот модуль строит два представления одной и той же регистровой карты:

- "логическое" (LogicalTopRegister / LogicalBlock) - как регистры описаны в
  YAML, без развёртки count/repeat в отдельные записи. Используется для
  человекочитаемой документации.
- "плоское" (FlatRegister) - полностью развёрнутый список, где одна запись
  соответствует ровно одному Modbus-адресу. Используется генератором C-кода
  и таблицей адресов в документации.

Оба представления строятся за один проход и используют общую валидацию полей
регистра (_validate_common), чтобы не проверять одно и то же дважды и не
дублировать сообщения об ошибках (в частности, для регистра внутри блока
валидация выполняется один раз для определения, а не по разу на каждый из
`repeat` экземпляров).

Перекрёстные проверки, требующие видеть модель целиком (уникальность итоговых
C-имён, пересечения адресов между разными регистрами/блоками), находятся в
modbus_regmodel.validate - сознательное разделение ответственности.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from .paths import OutputSpec, resolve_output_paths
from .types import (
    normalize_type,
    REGS_PER_TYPE,
    INDEXING_SCALAR,
    INDEXING_IDX,
    INDEXING_INST,
    INDEXING_INST_ELEM,
)

MODBUS_ADDR_MIN = 0x0000
MODBUS_ADDR_MAX = 0xFFFF

# Требование формата: [A-Z0-9_]+. Дополнительно (для безопасности - чтобы точно
# получить валидный C-идентификатор) запрещаем имя, начинающееся с цифры.
_NAME_RE = re.compile(r'^[A-Z_][A-Z0-9_]*$')


def is_valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


def _is_plain_int(value: Any) -> bool:
    """True только для настоящего int (bool в Python - подкласс int, его отсекаем)."""
    return isinstance(value, int) and not isinstance(value, bool)


def compute_access_mode(getter: Optional[str], setter: Optional[str]) -> str:
    if getter and setter:
        return "RW"
    if getter:
        return "RO"
    if setter:
        return "WO"
    return "RESERVED"


# --- Общие поля регистра, провалидированные один раз -----------------------

@dataclass
class _CommonFields:
    raw_addr: int                 # 'addr' для top-level или 'offset' внутри блока
    canonical_type: str
    regs_per_element: int
    count: Optional[int]
    reg_name: Optional[str]
    getter: Optional[str]
    setter: Optional[str]
    description: Optional[str]
    unit: Optional[str]


# --- Логическая (несвёрнутая) модель ----------------------------------------

@dataclass
class LogicalTopRegister:
    """Регистр верхнего уровня в том виде, как он описан в YAML (до развёртки count)."""
    addr: int
    canonical_type: str
    name: Optional[str]
    count: Optional[int]
    getter: Optional[str]
    setter: Optional[str]
    description: Optional[str]
    unit: Optional[str]

    @property
    def access_mode(self) -> str:
        return compute_access_mode(self.getter, self.setter)

    @property
    def regs_per_element(self) -> int:
        return REGS_PER_TYPE[self.canonical_type]

    @property
    def end_addr(self) -> int:
        """Последний занимаемый адрес с учётом count (без count - тот же addr)."""
        n = self.count or 1
        return self.addr + n * self.regs_per_element - 1


@dataclass
class LogicalBlockRegister:
    """Регистр внутри блока в том виде, как он описан в YAML (одно определение
    на все экземпляры блока, без развёртки repeat/count)."""
    offset: int
    canonical_type: str
    name: Optional[str]
    count: Optional[int]
    getter: Optional[str]
    setter: Optional[str]
    description: Optional[str]
    unit: Optional[str]

    @property
    def access_mode(self) -> str:
        return compute_access_mode(self.getter, self.setter)

    @property
    def regs_per_element(self) -> int:
        return REGS_PER_TYPE[self.canonical_type]

    @property
    def end_offset(self) -> int:
        n = self.count or 1
        return self.offset + n * self.regs_per_element - 1


@dataclass
class LogicalBlock:
    name: str
    start_addr: int
    repeat: int
    step: int
    registers: list[LogicalBlockRegister] = field(default_factory=list)


# --- Плоская (полностью развёрнутая) модель ---------------------------------

@dataclass
class FlatRegister:
    """Одна логическая запись плоской регистровой модели - соответствует ровно
    одному Modbus-адресу (началу одного элемента данных)."""

    id: str                      # человекочитаемый путь до записи в YAML (для диагностики)
    addr: int
    canonical_type: str
    getter: Optional[str]
    setter: Optional[str]
    description: Optional[str]
    unit: Optional[str]

    block_name: Optional[str] = None
    reg_name: Optional[str] = None
    instance_index: Optional[int] = None
    elem_index: Optional[int] = None

    @property
    def occupied(self) -> int:
        return REGS_PER_TYPE[self.canonical_type]

    @property
    def end_addr(self) -> int:
        return self.addr + self.occupied - 1

    @property
    def is_in_block(self) -> bool:
        return self.block_name is not None

    @property
    def is_array_element(self) -> bool:
        return self.elem_index is not None

    @property
    def indexing(self) -> str:
        if self.is_in_block:
            return INDEXING_INST_ELEM if self.is_array_element else INDEXING_INST
        return INDEXING_IDX if self.is_array_element else INDEXING_SCALAR

    @property
    def call_index_args(self) -> list[int]:
        """Аргументы-индексы в порядке, ожидаемом сгенерированной обёрткой
        (types.WrapperKey): сначала instance, затем elem."""
        if self.indexing == INDEXING_SCALAR:
            return []
        if self.indexing == INDEXING_IDX:
            return [self.elem_index]
        if self.indexing == INDEXING_INST:
            return [self.instance_index]
        return [self.instance_index, self.elem_index]

    @property
    def access_mode(self) -> str:
        return compute_access_mode(self.getter, self.setter)

    @property
    def c_name(self) -> Optional[str]:
        if self.reg_name is None:
            return None
        if self.is_in_block:
            base = f"{self.block_name}_{self.instance_index}_{self.reg_name}"
        else:
            base = f"REG_{self.reg_name}"
        if self.is_array_element:
            base = f"{base}_{self.elem_index}"
        return base


@dataclass
class ParseResult:
    registers: list[FlatRegister]
    top_registers: list[LogicalTopRegister]
    blocks: list[LogicalBlock]
    includes: list[str]
    output: OutputSpec
    errors: list[str]


def _empty_result(errors: list[str]) -> ParseResult:
    return ParseResult(
        registers=[], top_registers=[], blocks=[],
        includes=[], output=OutputSpec('', '', ''), errors=errors,
    )


def parse_spec(yaml_path: str) -> ParseResult:
    """Читает YAML, строит логическую и плоскую регистровые модели.

    Накапливает все найденные структурные ошибки, не останавливаясь на первой
    найденной (насколько это возможно без риска обращения к отсутствующим
    полям); при неисправимой структурной проблеме (например, `blocks[i]` -
    не словарь) дальнейший разбор этого элемента пропускается.
    """
    errors: list[str] = []
    flat: list[FlatRegister] = []
    top_registers: list[LogicalTopRegister] = []
    logical_blocks: list[LogicalBlock] = []

    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except OSError as e:
        return _empty_result([f"Не удалось открыть файл '{yaml_path}': {e}"])
    except yaml.YAMLError as e:
        return _empty_result([f"Ошибка разбора YAML: {e}"])

    if not isinstance(data, dict):
        return _empty_result(["Корень YAML-файла должен быть словарём (mapping)"])

    has_registers = isinstance(data.get('registers'), list)
    has_blocks = isinstance(data.get('blocks'), list)

    if not has_registers and not has_blocks:
        errors.append("Файл должен содержать хотя бы один из разделов: 'registers' или 'blocks'")

    def validate_common(
        reg_data: Any, ctx: str, addr_field: str, block_step: Optional[int],
    ) -> Optional[_CommonFields]:
        """Валидирует поля, общие для top-level регистра и регистра внутри
        блока. Выполняется РОВНО ОДИН РАЗ на каждое определение регистра в
        YAML (а не на каждый развёрнутый экземпляр/элемент) - иначе одна и та
        же структурная ошибка внутри блока задваивалась бы `repeat` раз."""
        if not isinstance(reg_data, dict):
            errors.append(f"[{ctx}] Элемент должен быть словарём")
            return None

        if addr_field not in reg_data:
            errors.append(f"[{ctx}] Отсутствует обязательное поле '{addr_field}'")
            return None

        raw_addr = reg_data[addr_field]
        if not _is_plain_int(raw_addr):
            errors.append(f"[{ctx}] Поле '{addr_field}' должно быть целым числом")
            return None
        if raw_addr < 0:
            errors.append(f"[{ctx}] Поле '{addr_field}' не может быть отрицательным")
            return None

        if 'type' not in reg_data:
            errors.append(f"[{ctx}] Отсутствует обязательное поле 'type'")
            return None

        canonical_type = normalize_type(reg_data['type'])
        if canonical_type is None:
            errors.append(f"[{ctx}] Неизвестный тип '{reg_data['type']}'")
            return None

        regs_per_element = REGS_PER_TYPE[canonical_type]

        count = reg_data.get('count')
        if count is not None:
            if not _is_plain_int(count) or count < 1:
                errors.append(f"[{ctx}] Поле 'count' должно быть целым числом >= 1")
                return None

        reg_name = reg_data.get('name')
        if reg_name is not None:
            if not isinstance(reg_name, str) or not is_valid_name(reg_name):
                errors.append(
                    f"[{ctx}] Имя '{reg_name}' недопустимо. "
                    f"Разрешены только [A-Z0-9_]+, не начиная с цифры"
                )
                reg_name = None

        # offset + occupied <= step - только для регистров внутри блока.
        if block_step is not None:
            total_occupied = (count or 1) * regs_per_element
            if raw_addr + total_occupied > block_step:
                errors.append(
                    f"[{ctx}] Регистр выходит за границу шага блока: "
                    f"offset (0x{raw_addr:02X}) + occupied ({total_occupied}) "
                    f"> step (0x{block_step:02X})"
                )

        getter = reg_data.get('getter')
        setter = reg_data.get('setter')
        if getter is not None and not isinstance(getter, str):
            errors.append(f"[{ctx}] Поле 'getter' должно быть строкой")
            getter = None
        if setter is not None and not isinstance(setter, str):
            errors.append(f"[{ctx}] Поле 'setter' должно быть строкой")
            setter = None

        description = reg_data.get('description')
        unit = reg_data.get('unit')

        return _CommonFields(
            raw_addr=raw_addr, canonical_type=canonical_type,
            regs_per_element=regs_per_element, count=count, reg_name=reg_name,
            getter=getter, setter=setter, description=description, unit=unit,
        )

    def expand_flat(
        common: _CommonFields, ctx: str, base_addr: int,
        block_name: Optional[str], instance_index: Optional[int],
    ) -> None:
        """Разворачивает одно провалидированное определение регистра в одну
        или несколько записей FlatRegister (по числу count, если задан)."""
        addr = base_addr + common.raw_addr

        def add_entry(elem_addr: int, elem_idx: Optional[int], entry_id: str) -> None:
            if elem_addr > MODBUS_ADDR_MAX:
                errors.append(f"[{entry_id}] Начальный адрес 0x{elem_addr:04X} выходит за пределы 0x0000..0xFFFF")
                return
            end = elem_addr + common.regs_per_element - 1
            if end > MODBUS_ADDR_MAX:
                errors.append(
                    f"[{entry_id}] Конечный адрес 0x{end:04X} "
                    f"(тип {common.canonical_type}) выходит за пределы 0xFFFF"
                )
                return
            flat.append(FlatRegister(
                id=entry_id, addr=elem_addr, canonical_type=common.canonical_type,
                getter=common.getter, setter=common.setter,
                description=common.description, unit=common.unit,
                block_name=block_name, reg_name=common.reg_name,
                instance_index=instance_index, elem_index=elem_idx,
            ))

        if common.count is not None:
            for elem_idx in range(common.count):
                elem_addr = addr + elem_idx * common.regs_per_element
                add_entry(elem_addr, elem_idx, f"{ctx}[{elem_idx}]")
        else:
            add_entry(addr, None, ctx)

    if has_registers:
        for i, reg in enumerate(data['registers']):
            ctx = f"registers[{i}]"
            common = validate_common(reg, ctx, addr_field='addr', block_step=None)
            if common is None:
                continue
            expand_flat(common, ctx, base_addr=0, block_name=None, instance_index=None)
            top_registers.append(LogicalTopRegister(
                addr=common.raw_addr, canonical_type=common.canonical_type,
                name=common.reg_name, count=common.count,
                getter=common.getter, setter=common.setter,
                description=common.description, unit=common.unit,
            ))

    if has_blocks:
        for b_idx, block in enumerate(data['blocks']):
            if not isinstance(block, dict):
                errors.append(f"[blocks[{b_idx}]] Элемент должен быть словарём")
                continue

            required = ('name', 'start_addr', 'repeat', 'step', 'registers')
            missing = [k for k in required if k not in block]
            for k in missing:
                errors.append(f"[blocks[{b_idx}]] Отсутствует обязательное поле '{k}'")
            if missing:
                continue

            block_name = block['name']
            if not isinstance(block_name, str) or not is_valid_name(block_name):
                errors.append(
                    f"[blocks[{b_idx}]] Имя блока '{block_name}' недопустимо. "
                    f"Разрешены только [A-Z0-9_]+, не начиная с цифры"
                )
                continue

            start_addr, repeat, step = block['start_addr'], block['repeat'], block['step']
            if not all(_is_plain_int(v) for v in (start_addr, repeat, step)):
                errors.append(f"[blocks[{b_idx}]('{block_name}')] start_addr, repeat и step должны быть целыми числами")
                continue
            if repeat < 1:
                errors.append(f"[blocks[{b_idx}]('{block_name}')] repeat должен быть >= 1")
                continue
            if step <= 0:
                errors.append(f"[blocks[{b_idx}]('{block_name}')] step должен быть положительным")
                continue
            if start_addr < 0:
                errors.append(f"[blocks[{b_idx}]('{block_name}')] start_addr не может быть отрицательным")
                continue

            block_regs = block['registers']
            if not isinstance(block_regs, list) or not block_regs:
                errors.append(f"[blocks[{b_idx}]('{block_name}')] 'registers' должен быть непустым списком")
                continue

            last_instance_start = start_addr + (repeat - 1) * step
            if last_instance_start > MODBUS_ADDR_MAX:
                errors.append(
                    f"[blocks[{b_idx}]('{block_name}')] Последний экземпляр блока начинается "
                    f"с 0x{last_instance_start:04X} - уже выходит за пределы 0xFFFF"
                )
                continue

            # Валидируем каждое определение регистра внутри блока РОВНО ОДИН
            # РАЗ (а не по разу на каждый из repeat экземпляров).
            validated: list[Optional[_CommonFields]] = []
            block_logical_regs: list[LogicalBlockRegister] = []
            for r_idx, reg in enumerate(block_regs):
                ctx0 = f"blocks[{b_idx}]('{block_name}').reg[{r_idx}]"
                common = validate_common(reg, ctx0, addr_field='offset', block_step=step)
                validated.append(common)
                if common is not None:
                    block_logical_regs.append(LogicalBlockRegister(
                        offset=common.raw_addr, canonical_type=common.canonical_type,
                        name=common.reg_name, count=common.count,
                        getter=common.getter, setter=common.setter,
                        description=common.description, unit=common.unit,
                    ))

            logical_blocks.append(LogicalBlock(
                name=block_name, start_addr=start_addr, repeat=repeat, step=step,
                registers=block_logical_regs,
            ))

            for inst in range(repeat):
                base_addr = start_addr + inst * step
                for r_idx, common in enumerate(validated):
                    if common is None:
                        continue
                    ctx = f"blocks[{b_idx}]('{block_name}').inst[{inst}].reg[{r_idx}]"
                    expand_flat(common, ctx, base_addr, block_name=block_name, instance_index=inst)

    includes = data.get('includes') or []
    if not isinstance(includes, list) or not all(isinstance(x, str) for x in includes):
        errors.append("Поле 'includes' должно быть списком строк")
        includes = []

    try:
        output = resolve_output_paths(yaml_path, data.get('output'))
    except ValueError as e:
        errors.append(str(e))
        output = OutputSpec('', '', '')

    return ParseResult(
        registers=flat, top_registers=top_registers, blocks=logical_blocks,
        includes=includes, output=output, errors=errors,
    )
