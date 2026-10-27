import os
import sys
import tempfile
import textwrap
import unittest

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modbus_regmodel.model import parse_spec
from modbus_regmodel.validate import validate_model
from modbus_regmodel.codegen import generate_header, generate_source
from modbus_regmodel.cli import run


def write_yaml(tmpdir: str, relpath: str, content: str) -> str:
    path = os.path.join(tmpdir, relpath)
    os.makedirs(os.path.dirname(path) or tmpdir, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(textwrap.dedent(content))
    return path


BASIC_YAML = """\
includes:
  - "sensor_api.h"

registers:
  - addr: 0x0001
    name: DEVICE_STATUS
    type: uint16
    getter: get_system_status

  - addr: 0x0002
    name: DEVICE_ENABLED
    type: bool
    getter: get_device_enabled
    setter: set_device_enabled

  - addr: 0x0010
    name: IGNITION_STATE
    type: uint8
    count: 3
    getter: ign_get_state
    setter: ign_set_state

  - addr: 0x0020
    type: float
    getter: get_supply_temperature

  - addr: 0x0030
    name: RESERVED_EXPANSION
    type: uint16
    count: 2

blocks:
  - name: CHANNEL
    start_addr: 0x0100
    repeat: 3
    step: 0x10
    registers:
      - name: TEMP_CURRENT
        type: float
        getter: ch_get_temp

      - name: SETPOINT_HISTORY
        type: float
        count: 2
        getter: ch_get_setpoint_history
        setter: ch_set_setpoint_history
"""


def parse_ok(tmp: str, name: str, text: str):
    path = write_yaml(tmp, name, text)
    result = parse_spec(path)
    return result


class TestParsing(unittest.TestCase):
    def test_basic_valid_file_has_no_structural_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", BASIC_YAML)
            self.assertEqual(result.errors, [])
            self.assertEqual(validate_model(result.registers, result.blocks), [])

    def test_basic_flat_count(self):
        # top-level: 1 + 1 + 3 + 1 + 2 = 8
        # block: 3 инстанса * (1 TEMP_CURRENT + 2 SETPOINT_HISTORY) = 9
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", BASIC_YAML)
            self.assertEqual(len(result.registers), 17)

    def test_count_1_still_uses_indexed_form(self):
        text = """
        registers:
          - addr: 0x0001
            name: X
            type: uint16
            count: 1
            getter: get_x
            setter: set_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertEqual(result.errors, [])
            reg = result.registers[0]
            self.assertEqual(reg.indexing, "idx")
            self.assertEqual(reg.c_name, "REG_X_0")

    def test_duplicate_name_detected(self):
        text = """
        registers:
          - addr: 0x0001
            name: DUP
            type: uint16
            getter: get_a
          - addr: 0x0002
            name: DUP
            type: uint16
            getter: get_b
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertEqual(result.errors, [])
            errors = validate_model(result.registers, result.blocks)
            self.assertTrue(any("Дублирование" in e for e in errors), errors)

    def test_duplicate_name_across_block_instances_is_allowed(self):
        # 'name' внутри block может повторяться в YAML - коллизия проверяется
        # уже по итоговому C-имени (CHANNEL_0_X, CHANNEL_1_X, ...), а не по 'name'.
        text = """
        blocks:
          - name: CH
            start_addr: 0x0100
            repeat: 3
            step: 0x10
            registers:
              - name: X
                type: uint16
                getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertEqual(result.errors, [])
            self.assertEqual(validate_model(result.registers, result.blocks), [])

    def test_overlap_between_adjacent_registers_detected(self):
        text = """
        registers:
          - addr: 0x0010
            type: float
            getter: get_a
          - addr: 0x0011
            type: uint16
            getter: get_b
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertEqual(result.errors, [])
            errors = validate_model(result.registers, result.blocks)
            self.assertTrue(any("Пересечение" in e for e in errors), errors)

    def test_overlap_hidden_behind_a_gap_is_still_detected(self):
        # A=[0x10,0x11] (float, occ2), B=[0x12,0x12] (occ1, не пересекает A),
        # C=[0x11,0x11] (occ1) - пересекает A, но НЕ соседствует с ним после
        # сортировки по адресу (между ними встаёт B). Регрессионный тест на
        # алгоритм проверки пересечений (см. validate._check_overlaps).
        text = """
        registers:
          - addr: 0x0010
            type: float
            getter: get_a
          - addr: 0x0011
            type: uint16
            getter: get_c
          - addr: 0x0012
            type: uint16
            getter: get_b
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertEqual(result.errors, [])
            errors = validate_model(result.registers, result.blocks)
            self.assertTrue(any("Пересечение" in e for e in errors), errors)

    def test_occupied_exceeds_step(self):
        # float занимает 2 регистра, step=1 — поле не помещается.
        text = """
        blocks:
          - name: CH
            start_addr: 0x0100
            repeat: 2
            step: 0x01
            registers:
              - type: float
                getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertTrue(any("границу шага" in e for e in result.errors), result.errors)

    def test_occupied_exactly_fitting_step_is_valid(self):
        # float занимает 2 регистра при step=2 — занимает [0,1],
        # следующий экземпляр начинается с 2 - ровно по границе, это НЕ нарушение.
        text = """
        blocks:
          - name: CH
            start_addr: 0x0100
            repeat: 2
            step: 0x02
            registers:
              - type: float
                getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertEqual(result.errors, [])

    def test_occupied_with_nested_count_exceeds_step(self):
        # float[count=2] занимает 4 регистра при step=3 — массив не помещается.
        text = """
        blocks:
          - name: CH
            start_addr: 0x0100
            repeat: 1
            step: 0x03
            registers:
              - type: float
                count: 2
                getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertTrue(any("границу шага" in e for e in result.errors), result.errors)

    def test_address_overflow_detected(self):
        text = """
        registers:
          - addr: 0xFFFF
            type: float
            getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertTrue(any("0xFFFF" in e for e in result.errors), result.errors)

    def test_block_last_instance_overflow_detected(self):
        text = """
        blocks:
          - name: CH
            start_addr: 0xFFF0
            repeat: 100
            step: 0x10
            registers:
              - type: uint16
                getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertTrue(any("0xFFFF" in e for e in result.errors), result.errors)

    def test_invalid_name_rejected(self):
        text = """
        registers:
          - addr: 0x0001
            name: "1BAD"
            type: uint16
            getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertTrue(any("недопустимо" in e for e in result.errors), result.errors)

    def test_reserved_register_has_no_getter_setter(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", BASIC_YAML)
            reserved = [r for r in result.registers if r.reg_name == "RESERVED_EXPANSION"]
            self.assertEqual(len(reserved), 2)
            for r in reserved:
                self.assertEqual(r.access_mode, "RESERVED")


class TestSequentialBlocks(unittest.TestCase):
    def parse_model(self, block, registers=None):
        data = {'blocks': [block]}
        if registers is not None:
            data['registers'] = registers
        with tempfile.TemporaryDirectory() as tmp:
            return parse_ok(tmp, 'reg.yaml', yaml.safe_dump(data))

    def block(self, **changes):
        block = {
            'name': 'CH', 'start_addr': 0x100, 'repeat': 2,
            'registers': [{'name': 'VALUE', 'type': 'uint16', 'getter': 'get_value'}],
        }
        block.update(changes)
        return block

    def test_offsets_include_arrays_and_reserved_fields(self):
        result = self.parse_model(self.block(registers=[
            {'name': 'FIRST', 'type': 'uint8', 'getter': 'get_first'},
            {'name': 'RESERVED_1', 'type': 'uint16', 'count': 3},
            {'name': 'VALUES', 'type': 'float', 'count': 2, 'getter': 'get_values'},
            {'type': 'uint32'},
            {'name': 'LAST', 'type': 'bool', 'getter': 'get_last'},
        ]))
        self.assertEqual(result.errors, [])
        self.assertEqual(validate_model(result.registers, result.blocks), [])
        block = result.blocks[0]
        self.assertEqual([r.offset for r in block.registers], [0, 1, 4, 8, 10])
        self.assertEqual(block.step, 11)
        self.assertEqual(block.end_addr, 0x115)
        values = [r for r in result.registers if r.reg_name == 'VALUES']
        self.assertEqual([r.addr for r in values], [0x104, 0x106, 0x10F, 0x111])
        self.assertEqual([r.call_index_args for r in values], [[0, 0], [0, 1], [1, 0], [1, 1]])

    def test_explicit_step_keeps_tail_and_instance_addresses(self):
        result = self.parse_model(self.block(step=16))
        self.assertEqual(result.errors, [])
        self.assertEqual([r.addr for r in result.registers], [0x100, 0x110])
        self.assertEqual(result.blocks[0].end_addr, 0x11F)

    def test_offset_is_rejected_even_when_zero_or_null(self):
        for offset in (0, 4, None):
            with self.subTest(offset=offset):
                result = self.parse_model(self.block(registers=[{'offset': offset, 'type': 'uint16'}]))
                self.assertEqual(len(result.errors), 1)
                self.assertIn('offset удалён из формата', result.errors[0])
                self.assertIn('RESERVED', result.errors[0])

    def test_invalid_step_is_rejected(self):
        for step in (0, -1, True, '16', 1.5, None):
            with self.subTest(step=step):
                result = self.parse_model(self.block(step=step))
                self.assertTrue(any('step' in e for e in result.errors), result.errors)

    def test_tail_overflow_is_rejected(self):
        result = self.parse_model(self.block(start_addr=0xFFFF, repeat=1, step=2))
        self.assertTrue(any('хвоста' in e and '0xFFFF' in e for e in result.errors), result.errors)

    def test_region_can_end_exactly_at_ffff(self):
        result = self.parse_model(self.block(start_addr=0xFFF0, repeat=1, step=16))
        self.assertEqual(result.errors, [])
        self.assertEqual(result.blocks[0].end_addr, 0xFFFF)

    def test_register_cannot_occupy_tail_of_any_instance(self):
        for addr in (0x101, 0x10F, 0x111, 0x11F):
            with self.subTest(addr=addr):
                result = self.parse_model(self.block(step=16), [{'addr': addr, 'type': 'uint16'}])
                self.assertEqual(result.errors, [])
                self.assertTrue(any('Пересечение' in e for e in validate_model(result.registers, result.blocks)))

    def test_register_just_after_block_is_allowed(self):
        result = self.parse_model(self.block(step=16), [{'addr': 0x120, 'type': 'uint16'}])
        self.assertEqual(result.errors, [])
        self.assertEqual(validate_model(result.registers, result.blocks), [])

    def test_block_cannot_occupy_another_blocks_tail(self):
        for start in (0x101, 0x11F):
            with self.subTest(start=start), tempfile.TemporaryDirectory() as tmp:
                result = parse_ok(tmp, 'reg.yaml', yaml.safe_dump({'blocks': [
                    self.block(step=16), self.block(name='OTHER', start_addr=start, repeat=1),
                ]}))
                self.assertEqual(result.errors, [])
                self.assertTrue(any('Пересечение' in e for e in validate_model(result.registers, result.blocks)))

    def test_reserved_fields_still_require_unique_names(self):
        result = self.parse_model(self.block(registers=[
            {'name': 'RESERVED_1', 'type': 'uint16'},
            {'name': 'RESERVED_1', 'type': 'uint16'},
        ]))
        self.assertEqual(result.errors, [])
        self.assertTrue(any('Дублирование' in e for e in validate_model(result.registers, result.blocks)))

    def test_top_level_reserved_names_are_also_checked(self):
        result = self.parse_model(self.block(), [
            {'addr': 1, 'name': 'RESERVED_1', 'type': 'uint16'},
            {'addr': 2, 'name': 'RESERVED_1', 'type': 'uint16'},
        ])
        self.assertEqual(result.errors, [])
        self.assertTrue(any('Дублирование' in e for e in validate_model(result.registers, result.blocks)))

    def test_unnamed_reserved_fields_are_allowed(self):
        result = self.parse_model(self.block(registers=[{'type': 'uint16'}, {'type': 'uint32'}]))
        self.assertEqual(result.errors, [])
        self.assertEqual(validate_model(result.registers, result.blocks), [])
        self.assertEqual(result.blocks[0].step, 3)

    def test_reserved_type_is_required(self):
        result = self.parse_model(self.block(registers=[{'name': 'RESERVED_1', 'count': 2}]))
        self.assertTrue(any("обязательное поле 'type'" in e for e in result.errors), result.errors)


class TestCodegen(unittest.TestCase):
    def test_header_is_static_and_minimal(self):
        h = generate_header()
        self.assertIn("__MODBUS_REG_MODEL_H__", h)
        self.assertIn("void ModbusRegModelInit(void);", h)
        self.assertNotIn("#define REG_", h)  # адреса не должны утекать в .h

    def test_reserved_register_has_no_define_or_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", BASIC_YAML)
            regs = sorted(result.registers, key=lambda r: r.addr)
            src = generate_source(regs, result.includes)
            self.assertNotIn("#define REG_RESERVED_EXPANSION_0", src)
            self.assertNotIn("case REG_RESERVED_EXPANSION_0:", src)

    def test_bool_uses_reg16_both_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", BASIC_YAML)
            regs = sorted(result.registers, key=lambda r: r.addr)
            src = generate_source(regs, result.includes)
            self.assertIn("modbus_slave_read_holding_reg16(ctx, &raw)", src)
            self.assertIn("modbus_slave_write_holding_reg16(ctx, &raw)", src)

    def test_uint8_uses_reg8_not_reg16(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", BASIC_YAML)
            regs = sorted(result.registers, key=lambda r: r.addr)
            src = generate_source(regs, result.includes)
            self.assertIn("modbus_slave_read_holding_reg8(ctx, &val)", src)
            self.assertIn("modbus_slave_write_holding_reg8(ctx, &val)", src)

    def test_float_write_is_atomic_via_reg32(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", BASIC_YAML)
            regs = sorted(result.registers, key=lambda r: r.addr)
            src = generate_source(regs, result.includes)
            self.assertRegex(src, r"if \(modbus_slave_write_holding_reg32\(ctx, &raw\)\)")

    def test_only_used_wrappers_are_emitted(self):
        text = """
        registers:
          - addr: 0x0001
            type: uint16
            getter: get_only
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            regs = sorted(result.registers, key=lambda r: r.addr)
            src = generate_source(regs, result.includes)
            self.assertIn("static void read_reg16_u16", src)
            self.assertNotIn("write_reg16_u16", src)
            self.assertNotIn("f32", src)
            # <stdbool.h> подключается всегда, но никакая bool-обёртка/переменная
            # не должна генерироваться, если в модели нет ни одного bool-регистра.
            self.assertNotIn("bool val", src)
            self.assertNotIn("(bool)(raw", src)

    def test_block_array_uses_two_indices_in_correct_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", BASIC_YAML)
            regs = sorted(result.registers, key=lambda r: r.addr)
            src = generate_source(regs, result.includes)
            # Внутри обёртки индексы передаются в getter/setter как (inst, elem)
            self.assertIn("float val = getter(inst, elem);", src)
            self.assertIn("setter(inst, elem, val);", src)
            # В самом case для CHANNEL[1].SETPOINT_HISTORY[0] обёртка вызывается
            # как (context, <getter>, instance_index=1, elem_index=0)
            self.assertIn("read_reg32_f32_inst_elem(context, ch_get_setpoint_history, 1, 0)", src)


class TestOutputPathResolution(unittest.TestCase):
    def test_default_paths_next_to_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(tmp, "reg.yaml", "registers:\n  - addr: 1\n    type: uint16\n    getter: f\n")
            rc = run(path, dry_run=False)
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "modbus_reg_model.h")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "modbus_reg_model.c")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "modbus_reg_model.md")))

    def test_relative_paths_with_parent_traversal(self):
        text = """
        output:
          header: "../source/modbus_reg_model.h"
          source: "../source/modbus_reg_model.c"
          docs: "../docs/regmodel.md"

        registers:
          - addr: 1
            type: uint16
            getter: f
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(tmp, "data/reg.yaml", text)
            rc = run(path, dry_run=False)
            self.assertEqual(rc, 0)
            expected_h = os.path.normpath(os.path.join(tmp, "source", "modbus_reg_model.h"))
            expected_c = os.path.normpath(os.path.join(tmp, "source", "modbus_reg_model.c"))
            expected_md = os.path.normpath(os.path.join(tmp, "docs", "regmodel.md"))
            self.assertTrue(os.path.isfile(expected_h), expected_h)
            self.assertTrue(os.path.isfile(expected_c), expected_c)
            self.assertTrue(os.path.isfile(expected_md), expected_md)

    def test_dry_run_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(tmp, "reg.yaml", "registers:\n  - addr: 1\n    type: uint16\n    getter: f\n")
            rc = run(path, dry_run=True)
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.isfile(os.path.join(tmp, "modbus_reg_model.h")))
            self.assertFalse(os.path.isfile(os.path.join(tmp, "modbus_reg_model.c")))
            self.assertFalse(os.path.isfile(os.path.join(tmp, "modbus_reg_model.md")))

    def test_invalid_yaml_returns_nonzero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(tmp, "reg.yaml", "registers:\n  - addr: 1\n    type: not_a_type\n    getter: f\n")
            rc = run(path, dry_run=False)
            self.assertEqual(rc, 1)
            self.assertFalse(os.path.isfile(os.path.join(tmp, "modbus_reg_model.c")))
            self.assertFalse(os.path.isfile(os.path.join(tmp, "modbus_reg_model.md")))


if __name__ == "__main__":
    unittest.main()
