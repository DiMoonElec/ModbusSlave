import os
import sys
import tempfile
import textwrap
import unittest

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
      - offset: 0x00
        name: TEMP_CURRENT
        type: float
        getter: ch_get_temp

      - offset: 0x02
        name: SETPOINT_HISTORY
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
            self.assertEqual(validate_model(result.registers), [])

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
            errors = validate_model(result.registers)
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
              - offset: 0x00
                name: X
                type: uint16
                getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertEqual(result.errors, [])
            self.assertEqual(validate_model(result.registers), [])

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
            errors = validate_model(result.registers)
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
            errors = validate_model(result.registers)
            self.assertTrue(any("Пересечение" in e for e in errors), errors)

    def test_offset_plus_occupied_exceeds_step(self):
        # float занимает 2 регистра, offset=0x00, step=0x01 -> 0+2 > 1, нарушение.
        text = """
        blocks:
          - name: CH
            start_addr: 0x0100
            repeat: 2
            step: 0x01
            registers:
              - offset: 0x00
                type: float
                getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertTrue(any("границу шага" in e for e in result.errors), result.errors)

    def test_offset_plus_occupied_exactly_fitting_step_is_valid(self):
        # float занимает 2 регистра, offset=0x00, step=0x02 -> занимает [0,1],
        # следующий экземпляр начинается с 2 - ровно по границе, это НЕ нарушение.
        text = """
        blocks:
          - name: CH
            start_addr: 0x0100
            repeat: 2
            step: 0x02
            registers:
              - offset: 0x00
                type: float
                getter: get_x
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", text)
            self.assertEqual(result.errors, [])

    def test_offset_plus_occupied_with_nested_count_exceeds_step(self):
        # float[count=2] занимает 4 регистра, offset=0x00, step=0x03 -> 0+4 > 3, нарушение.
        text = """
        blocks:
          - name: CH
            start_addr: 0x0100
            repeat: 1
            step: 0x03
            registers:
              - offset: 0x00
                type: float
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
              - offset: 0x00
                type: uint16
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


class TestCodegen(unittest.TestCase):
    def test_header_is_static_and_minimal(self):
        h = generate_header()
        self.assertIn("__MODBUS_REG_MODEL_H__", h)
        self.assertIn("void ModbusRegModelInit(void);", h)
        self.assertNotIn("#define REG_", h)  # адреса не должны утекать в .h

    def test_reserved_register_has_define_but_no_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_ok(tmp, "reg.yaml", BASIC_YAML)
            regs = sorted(result.registers, key=lambda r: r.addr)
            src = generate_source(regs, result.includes)
            self.assertIn("#define REG_RESERVED_EXPANSION_0", src)
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
