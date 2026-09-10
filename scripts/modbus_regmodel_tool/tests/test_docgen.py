import os
import re
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modbus_regmodel.docgen import generate_markdown
from modbus_regmodel.model import parse_spec
from modbus_regmodel.validate import validate_model

DEMO_YAML = """\
registers:
  - addr: 0x0001
    name: DEVICE_STATUS
    type: uint16
    getter: get_system_status
    description: "Текущее состояние устройства"

  - addr: 0x0002
    name: DEVICE_ENABLED
    type: bool
    getter: get_device_enabled
    setter: set_device_enabled

  - addr: 0x0010
    name: IGNITION_STATE
    type: uint8
    count: 12
    getter: ign_get_state
    setter: ign_set_state
    description: "Состояние каналов розжига"

  - addr: 0x0030
    type: float
    getter: get_supply_temperature
    unit: "°C"

  - addr: 0x0040
    name: RESERVED_EXPANSION
    type: uint16
    count: 8

blocks:
  - name: CHANNEL
    start_addr: 0x0100
    repeat: 12
    step: 0x10
    registers:
      - offset: 0x00
        name: TEMP_CURRENT
        type: float
        getter: ch_get_temp
        unit: "°C"
        description: "Текущая температура канала"
      - offset: 0x02
        name: SETPOINT_HISTORY
        type: float
        count: 2
        getter: ch_get_setpoint_history
        setter: ch_set_setpoint_history
        unit: "°C"
"""


def build(tmp: str, text: str):
    path = os.path.join(tmp, "reg.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(text))
    result = parse_spec(path)
    assert result.errors == [], result.errors
    assert validate_model(result.registers) == []
    return result


class TestDocgen(unittest.TestCase):
    def test_intro_mentions_key_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(tmp, DEMO_YAML)
            md = generate_markdown(result)
            self.assertIn("holding-регистры", md)
            self.assertIn("16 бит", md)
            self.assertIn("одним запросом", md)
            self.assertIn("`bool`", md)
            self.assertIn("false", md)
            self.assertIn("true", md)

    def test_no_getter_setter_leaked_into_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(tmp, DEMO_YAML)
            md = generate_markdown(result)
            for fn in ("get_system_status", "set_device_enabled", "ign_get_state",
                       "ign_set_state", "ch_get_temp", "ch_set_setpoint_history"):
                self.assertNotIn(fn, md)

    def test_top_level_array_shown_as_range_not_exploded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(tmp, DEMO_YAML)
            md = generate_markdown(result)
            # IGNITION_STATE (count=12) должен быть ОДНОЙ строкой-диапазоном,
            # а не 12 отдельными строками, во втором разделе документа.
            section2 = md.split("## 3.")[0]
            self.assertIn("IGNITION_STATE", section2)
            self.assertIn("16 .. 27 (0x0010 .. 0x001B)", section2)
            self.assertEqual(section2.count("IGNITION_STATE"), 1)

    def test_reserved_register_shown_with_reserved_access_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(tmp, DEMO_YAML)
            md = generate_markdown(result)
            section2 = md.split("## 3.")[0]
            self.assertIn("RESERVED_EXPANSION", section2)
            self.assertIn("RESERVED", section2)

    def test_block_shown_once_not_per_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(tmp, DEMO_YAML)
            md = generate_markdown(result)
            section3 = md.split("## 3.")[1].split("## 4.")[0]
            # Блок описан один раз, с параметрами repeat/step, а не 12 раз.
            self.assertEqual(section3.count("### Блок `CHANNEL`"), 1)
            self.assertIn("Количество экземпляров: 12", section3)
            self.assertIn("TEMP_CURRENT", section3)
            self.assertIn("SETPOINT_HISTORY", section3)
            # TEMP_CURRENT - float без count, но float всегда занимает 2 регистра,
            # поэтому даже одиночное значение показывается диапазоном смещений.
            self.assertIn("0 .. 1 (0x00 .. 0x01)", section3)
            self.assertIn("2 .. 5 (0x02 .. 0x05)", section3)

    def test_flat_table_has_full_expansion_with_generated_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(tmp, DEMO_YAML)
            md = generate_markdown(result)
            section4 = md.split("## 4.")[1]
            self.assertIn("| 1 | 0x0001 | REG_DEVICE_STATUS | uint16_t | RO |", section4)
            self.assertIn("| 256 .. 257 | 0x0100 .. 0x0101 | CHANNEL_0_TEMP_CURRENT | float | RO |", section4)
            self.assertIn("CHANNEL_1_SETPOINT_HISTORY_0", section4)
            self.assertIn("CHANNEL_1_SETPOINT_HISTORY_1", section4)

            data_rows = [
                line for line in section4.splitlines()
                if re.match(r'^\| \d+', line)
            ]
            # 5 top-level определений (1 + 1 + 12 + 1 + 8 = 23 записи) +
            # 12 экземпляров блока * (1 TEMP_CURRENT + 2 SETPOINT_HISTORY) = 36.
            self.assertEqual(len(data_rows), 23 + 36)

    def test_flat_table_shows_dec_and_hex_range_for_two_register_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(tmp, DEMO_YAML)
            md = generate_markdown(result)
            section4 = md.split("## 4.")[1]
            # unnamed float @ 0x0030 занимает 2 регистра (0x0030..0x0031)
            self.assertIn("| 48 .. 49 | 0x0030 .. 0x0031 | — | float | RO |", section4)
            # uint16_t занимает 1 регистр - диапазон не нужен
            self.assertIn("| 1 | 0x0001 |", section4)

    def test_unnamed_register_shown_with_dash_in_flat_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(tmp, DEMO_YAML)
            md = generate_markdown(result)
            section4 = md.split("## 4.")[1]
            self.assertIn("| 48 .. 49 | 0x0030 .. 0x0031 | — |", section4)

    def test_empty_sections_handled_gracefully(self):
        text = """
        registers:
          - addr: 1
            type: uint16
            getter: f
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = build(tmp, text)
            md = generate_markdown(result)
            self.assertIn("нет блоков", md)


if __name__ == "__main__":
    unittest.main()
