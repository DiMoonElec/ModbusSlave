"""Адресация, валидация и документация раскладки по полям."""
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modbus_regmodel.model import parse_spec
from modbus_regmodel.validate import validate_model
from modbus_regmodel.codegen import generate_source
from modbus_regmodel.docgen import generate_markdown


class TestPlanarBlocks(unittest.TestCase):
    def block(self, **changes):
        block = {
            'name': 'P', 'start_addr': 1001, 'repeat': 3,
            'registers': [
                {'name': 'STATE', 'type': 'uint16', 'getter': 'get_state'},
                {'name': 'VALUE', 'type': 'uint32', 'getter': 'get_value', 'setter': 'set_value'},
                {'name': 'TEMP', 'type': 'float', 'getter': 'get_temp', 'unit': '°C', 'description': 'A | B'},
            ],
        }
        block.update(changes)
        return block

    def parse(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'reg.yaml')
            path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding='utf-8')
            return parse_spec(str(path))

    def parse_block(self, **changes):
        return self.parse({'planar_blocks': [self.block(**changes)]})

    def assert_valid(self, result):
        self.assertEqual(result.errors, [])
        self.assertEqual(validate_model(result.registers, result.blocks), [])

    def test_planar_only_file_and_default_capacity(self):
        result = self.parse_block()
        self.assert_valid(result)
        self.assertEqual(result.blocks[0].capacity, 3)
        self.assertEqual(result.blocks[0].end_addr, 1015)
        self.assertEqual([r.offset for r in result.blocks[0].registers], [0, 3, 9])
        self.assertEqual(len(result.registers), 9)
        self.assertTrue(all(r.is_planar for r in result.registers))

    def test_mixed_sizes_with_odd_start_and_capacity(self):
        result = self.parse_block(capacity=7)
        self.assert_valid(result)
        for name, addresses in (
            ('STATE', [1001, 1002, 1003]),
            ('VALUE', [1008, 1010, 1012]),
            ('TEMP', [1022, 1024, 1026]),
        ):
            regs = [r for r in result.registers if r.reg_name == name]
            self.assertEqual([r.addr for r in regs], addresses)
            self.assertEqual([r.call_index_args for r in regs], [[0], [1], [2]])
            self.assertTrue(all(r.indexing == 'inst' for r in regs))
        self.assertEqual(result.blocks[0].end_addr, 1035)

    def test_single_word_fields_use_repeat_as_default_capacity(self):
        result = self.parse_block(registers=[{'type': 'bool'}, {'type': 'int8'}])
        self.assert_valid(result)
        self.assertEqual(result.blocks[0].capacity, 3)

    def test_reserved_column_keeps_following_field_position(self):
        fields = self.block()['registers']
        fields.insert(1, {'name': 'RESERVED_1', 'type': 'uint16'})
        fields.insert(2, {'type': 'uint16'})
        result = self.parse_block(capacity=8, registers=fields)
        self.assert_valid(result)
        self.assertEqual([r.addr for r in result.registers if r.reg_name == 'VALUE'], [1025, 1027, 1029])
        self.assertEqual(result.blocks[0].end_addr, 1056)
        source = generate_source(sorted(result.registers, key=lambda r: r.addr), [])
        self.assertNotIn('#define P_RESERVED_1', source)
        self.assertNotIn('case P_RESERVED_1', source)

    def test_reserved_type_participates_in_default_capacity(self):
        result = self.parse_block(registers=[{'type': 'uint32'}, {'type': 'uint16', 'getter': 'get_state'}])
        self.assert_valid(result)
        self.assertEqual(result.blocks[0].capacity, 3)
        self.assertEqual([r.addr for r in result.registers if r.getter], [1007, 1008, 1009])

    def test_count_key_is_forbidden_including_null_and_one(self):
        for count in (None, 1, 2, 0, False):
            for active in (False, True):
                with self.subTest(count=count, active=active):
                    field = {'type': 'uint16', 'count': count}
                    if active:
                        field['getter'] = 'get_state'
                    result = self.parse_block(registers=[field])
                    self.assertTrue(any('count запрещён' in e for e in result.errors), result.errors)

    def test_removed_offset_is_rejected(self):
        result = self.parse_block(registers=[{'type': 'uint16', 'offset': 0}])
        self.assertTrue(any('offset удалён' in e for e in result.errors), result.errors)

    def test_reserved_type_is_required(self):
        result = self.parse_block(registers=[{'name': 'RESERVED_1'}])
        self.assertTrue(any("обязательное поле 'type'" in e for e in result.errors), result.errors)

    def test_capacity_smaller_than_repeat_is_rejected(self):
        result = self.parse_block(capacity=2)
        self.assertTrue(any('capacity (2)' in e and 'repeat (3)' in e for e in result.errors), result.errors)

    def test_invalid_capacity_is_rejected(self):
        for capacity in (None, 0, -1, True, '7', 7.5):
            with self.subTest(capacity=capacity):
                result = self.parse_block(capacity=capacity)
                self.assertTrue(any('capacity' in e for e in result.errors), result.errors)

    def test_step_is_rejected_even_when_capacity_is_present(self):
        for changes in ({'step': 7}, {'step': None, 'capacity': 7}):
            with self.subTest(changes=changes):
                result = self.parse_block(**changes)
                self.assertTrue(any('step запрещён' in e for e in result.errors), result.errors)

    def test_capacity_is_rejected_in_ordinary_blocks(self):
        for capacity in (None, 3):
            with self.subTest(capacity=capacity):
                result = self.parse({'blocks': [self.block(capacity=capacity)]})
                self.assertTrue(any('capacity запрещён' in e for e in result.errors), result.errors)

    def test_capacity_reserves_same_number_of_elements_for_mixed_types(self):
        result = self.parse_block(start_addr=5000, repeat=2, capacity=3, registers=[
            {'name': 'P', 'type': 'uint16', 'getter': 'get_p'},
            {'name': 'Q', 'type': 'uint32', 'getter': 'get_q'},
        ])
        self.assert_valid(result)
        self.assertEqual([r.offset for r in result.blocks[0].registers], [0, 3])
        self.assertEqual([r.addr for r in result.registers], [5000, 5003, 5001, 5005])
        self.assertEqual(result.blocks[0].end_addr, 5008)
        self.assertEqual(len(result.registers), 4)

    def test_invalid_block_fields_are_rejected(self):
        for changes in (
            {'start_addr': -1}, {'start_addr': True}, {'repeat': 0}, {'repeat': True},
            {'repeat': 1.5}, {'registers': []}, {'registers': {}}, {'name': '1BAD'},
        ):
            with self.subTest(changes=changes):
                self.assertTrue(self.parse_block(**changes).errors)

    def test_missing_required_fields_are_rejected(self):
        for key in ('name', 'start_addr', 'repeat', 'registers'):
            with self.subTest(key=key):
                block = self.block()
                del block[key]
                self.assertTrue(self.parse({'planar_blocks': [block]}).errors)

    def test_non_list_section_is_rejected_even_with_registers(self):
        result = self.parse({'registers': [{'addr': 1, 'type': 'uint16'}], 'planar_blocks': {}})
        self.assertTrue(any("'planar_blocks' должно быть списком" in e for e in result.errors))

    def test_non_mapping_block_or_field_is_rejected(self):
        self.assertTrue(self.parse({'planar_blocks': [None]}).errors)
        self.assertTrue(self.parse_block(registers=[None]).errors)

    def test_full_last_column_tail_must_fit_address_space(self):
        fields = [{'type': 'uint16'}]
        self.assert_valid(self.parse_block(start_addr=65530, repeat=2, capacity=6, registers=fields))
        result = self.parse_block(start_addr=65530, repeat=2, capacity=7, registers=fields)
        self.assertTrue(any('хвоста' in e and '0xFFFF' in e for e in result.errors), result.errors)

    def test_entire_address_space_can_be_one_column(self):
        result = self.parse_block(start_addr=0, repeat=1, capacity=65536, registers=[{'type': 'uint16'}])
        self.assert_valid(result)
        self.assertEqual(result.blocks[0].end_addr, 65535)

    def test_registers_cannot_occupy_elements_or_column_tails(self):
        for addr in (1001, 1004, 1007, 1010, 1014, 1035):
            with self.subTest(addr=addr):
                result = self.parse({
                    'planar_blocks': [self.block(capacity=7)],
                    'registers': [{'addr': addr, 'type': 'uint16'}],
                })
                self.assertEqual(result.errors, [])
                self.assertTrue(any('Пересечение' in e for e in validate_model(result.registers, result.blocks)))

    def test_register_just_after_region_is_allowed(self):
        result = self.parse({'planar_blocks': [self.block(capacity=7)], 'registers': [{'addr': 1036, 'type': 'uint16'}]})
        self.assert_valid(result)

    def test_block_overlap_is_rejected_for_both_layouts(self):
        for section in ('blocks', 'planar_blocks'):
            with self.subTest(section=section):
                data = {'planar_blocks': [self.block(capacity=7)]}
                other = {'name': 'OTHER', 'start_addr': 1035, 'repeat': 1, 'registers': [{'type': 'uint16'}]}
                data.setdefault(section, []).append(other)
                result = self.parse(data)
                self.assertEqual(result.errors, [])
                self.assertTrue(any('Пересечение' in e for e in validate_model(result.registers, result.blocks)))

    def test_block_names_are_unique_across_both_layouts(self):
        for section in ('blocks', 'planar_blocks'):
            with self.subTest(section=section):
                data = {'planar_blocks': [self.block()]}
                data.setdefault(section, []).append(self.block(start_addr=2000))
                result = self.parse(data)
                self.assertTrue(any('Дублирование имени блока' in e for e in result.errors), result.errors)

    def test_duplicate_reserved_names_are_rejected(self):
        result = self.parse_block(registers=[{'name': 'R', 'type': 'uint16'}, {'name': 'R', 'type': 'uint16'}])
        self.assertEqual(result.errors, [])
        self.assertTrue(any('Дублирование' in e for e in validate_model(result.registers, result.blocks)))

    def test_generated_name_collisions_with_top_level_are_rejected(self):
        result = self.parse({
            'planar_blocks': [self.block(name='REG')],
            'registers': [{'addr': 1, 'name': 'STATE', 'type': 'uint16', 'count': 1}],
        })
        self.assertEqual(result.errors, [])
        self.assertTrue(any('REG_STATE_0' in e for e in validate_model(result.registers, result.blocks)))

    def test_codegen_uses_field_instance_names_and_constant_calls(self):
        result = self.parse_block(capacity=7)
        self.assert_valid(result)
        source = generate_source(sorted(result.registers, key=lambda r: r.addr), [])
        self.assertIn('#define P_VALUE_2', source)
        self.assertIn('case P_VALUE_2:', source)
        self.assertIn('read_reg32_u32_inst(context, get_value, 2);', source)
        self.assertIn('write_reg32_u32_inst(context, set_value, 2);', source)
        self.assertNotIn('case P_2_VALUE:', source)
        self.assertEqual(source.count('switch (reg)'), 2)

    def test_documentation_has_column_ranges_formula_and_flat_names(self):
        result = self.parse_block(capacity=7)
        self.assert_valid(result)
        md = generate_markdown(result)
        self.assertIn('### Planar-блок `P`', md)
        self.assertIn('Количество экземпляров: 3', md)
        self.assertIn('Вместимость каждой колонки (capacity): 7', md)
        self.assertIn('Область блока: 1001 .. 1035', md)
        self.assertIn('| 1 | VALUE | uint32_t | RW | 1008 .. 1013', md)
        self.assertIn('| 2 | TEMP | float | RO | 1022 .. 1027', md)
        self.assertIn('A \\| B | °C', md)
        self.assertIn('1001 + 0 + 1 * 1 = 1002', md)
        self.assertIn('| 1012 .. 1013 | 0x03F4 .. 0x03F5 | P_VALUE_2 |', md)

    def test_single_instance_documentation_example_uses_instance_zero(self):
        result = self.parse_block(repeat=1)
        self.assert_valid(result)
        self.assertIn('1001 + 0 + 0 * 1 = 1001', generate_markdown(result))


if __name__ == '__main__':
    unittest.main()
