"""Проверка сгенерированных обработчиков с настоящим PDU-парсером библиотеки."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_compile import COMPILER, compile_c
from modbus_regmodel.cli import run


MODEL = """\
includes:
  - "device_api.h"
blocks:
  - name: CHANNEL
    start_addr: 256
    repeat: 2
    step: 8
    registers:
      - name: VALUE
        type: uint16
        getter: get_value
        setter: set_value
      - name: RESERVED_1
        type: uint16
        count: 2
      - name: STATUS
        type: uint16
        getter: get_status
      - name: WIDE
        type: uint32
        getter: get_wide
        setter: set_wide
"""

DEVICE_API = """\
#include <stdint.h>
uint16_t get_value(uint16_t instance);
void set_value(uint16_t instance, uint16_t value);
uint16_t get_status(uint16_t instance);
uint32_t get_wide(uint16_t instance);
void set_wide(uint16_t instance, uint32_t value);
"""

PLANAR_MODEL = MODEL + """
planar_blocks:
  - name: PLANAR
    start_addr: 1001
    repeat: 2
    capacity: 5
    registers:
      - name: VALUE
        type: uint16
        getter: get_value
        setter: set_value
      - name: STATUS
        type: uint16
        getter: get_status
      - name: WIDE
        type: uint32
        getter: get_wide
        setter: set_wide
      - name: RESERVED_1
        type: uint16
"""

HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "modbus_reg_model.h"
#include "device_api.h"
#include "inc/modbus_slave_pdu_parser.h"

static uint16_t values[2] = {0x1234, 0x5678};
static uint32_t wide[2] = {0x12345678, 0x9ABCDEF0};
static unsigned writes;

uint16_t get_value(uint16_t instance) { return values[instance]; }
void set_value(uint16_t instance, uint16_t value) { values[instance] = value; ++writes; }
uint16_t get_status(uint16_t instance) { return (uint16_t)(0xAA00 + instance); }
uint32_t get_wide(uint16_t instance) { return wide[instance]; }
void set_wide(uint16_t instance, uint32_t value) { wide[instance] = value; ++writes; }

static void read_words(uint16_t addr, uint16_t count, const uint16_t *expected)
{
    uint8_t req[] = {3, (uint8_t)(addr >> 8), (uint8_t)addr, 0, (uint8_t)count};
    uint8_t resp[64];
    memset(resp, 0xFF, sizeof(resp));
    uint16_t len = modbus_slave_pdu_parse(req, sizeof(req), resp, sizeof(resp), 0);
    assert(len == 2 + 2 * count);
    assert(resp[0] == 3 && resp[1] == 2 * count);
    for (uint16_t i = 0; i < count; ++i)
        assert((((uint16_t)resp[2 + 2 * i] << 8) | resp[3 + 2 * i]) == expected[i]);
}

static void write_words(uint16_t addr, uint16_t count, const uint16_t *words)
{
    uint8_t req[64] = {16, (uint8_t)(addr >> 8), (uint8_t)addr, 0, (uint8_t)count, (uint8_t)(2 * count)};
    uint8_t resp[64];
    for (uint16_t i = 0; i < count; ++i) {
        req[6 + 2 * i] = (uint8_t)(words[i] >> 8);
        req[7 + 2 * i] = (uint8_t)words[i];
    }
    uint16_t len = modbus_slave_pdu_parse(req, (uint16_t)(6 + 2 * count), resp, sizeof(resp), 0);
    assert(len == 5 && resp[0] == 16);
    assert(memcmp(resp + 1, req + 1, 4) == 0);
}

int main(void)
{
    ModbusRegModelInit();
    /* Поля, явные резервы, хвосты и переход к следующему экземпляру. */
    const uint16_t expected[] = {
        0x1234, 0, 0, 0xAA00, 0x1234, 0x5678, 0, 0,
        0x5678, 0, 0, 0xAA01, 0x9ABC, 0xDEF0, 0, 0, 0
    };
    read_words(256, 17, expected);
    const uint16_t zero[] = {0};
    read_words(0, 1, zero);
    read_words(65535, 1, zero);

    /* Пустые адреса и RO не вызывают setter и не дают исключений. */
    const uint16_t ignored[] = {0xFFFF, 0xFFFF, 0xFFFF};
    write_words(257, 3, ignored);
    write_words(262, 2, ignored);
    write_words(272, 1, ignored);
    write_words(65535, 1, ignored);
    assert(writes == 0);

    /* Запись через резерв и хвост не сбивает адреса и индексы полей. */
    const uint16_t new_values[] = {0xBEEF, 9, 9, 9, 0x1122, 0x3344, 9, 9, 0xCAFE};
    write_words(256, 9, new_values);
    assert(writes == 3);
    assert(values[0] == 0xBEEF && values[1] == 0xCAFE);
    assert(wide[0] == 0x11223344);

    /* Обращение со второго слова пока сохраняет ноль/игнорирование. */
    read_words(261, 1, zero);
    write_words(261, 1, ignored);
    assert(writes == 3 && wide[0] == 0x11223344);

    /* Неполная запись с первого слова не вызывает setter. */
    uint8_t req[] = {16, 1, 4, 0, 1, 2, 0xFF, 0xFF};
    uint8_t resp[8];
    assert(modbus_slave_pdu_parse(req, sizeof(req), resp, sizeof(resp), 0) == 2);
    assert(resp[0] == 0x90 && resp[1] == 3);
    assert(writes == 3 && wide[0] == 0x11223344);
    return 0;
}
"""

PLANAR_MAIN = r"""
int main(void)
{
    ModbusRegModelInit();
    /* Колонки разной ширины с хвостами и последней резервной колонкой. */
    const uint16_t expected[] = {
        0x1234, 0x5678, 0, 0, 0,
        0xAA00, 0xAA01, 0, 0, 0,
        0x1234, 0x5678, 0x9ABC, 0xDEF0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0
    };
    read_words(1001, 25, expected);
    const uint16_t zero[] = {0};
    read_words(1000, 1, zero);
    read_words(1026, 1, zero);
    read_words(1012, 1, zero); /* Второе слово — пока ноль. */
    const uint16_t ignored[] = {0xFFFF};
    write_words(1003, 1, ignored);
    write_words(1006, 1, ignored); /* RO */
    write_words(1012, 1, ignored); /* Второе слово */
    write_words(1025, 1, ignored); /* Хвост последней колонки */
    write_words(1026, 1, ignored); /* Вне области */
    assert(writes == 0);

    /* Запись пересекает границы колонок, хвосты и RO. */
    const uint16_t new_values[] = {
        0xBEEF, 0xCAFE, 9, 9, 9,
        9, 9, 9, 9, 9,
        0x1122, 0x3344, 0x5566, 0x7788, 9
    };
    write_words(1001, 15, new_values);
    assert(writes == 4);
    assert(values[0] == 0xBEEF && values[1] == 0xCAFE);
    assert(wide[0] == 0x11223344 && wide[1] == 0x55667788);
    /* Обычный блок по старым адресам вызывает те же функции. */
    const uint16_t first[] = {0xBEEF};
    const uint16_t last[] = {0xCAFE};
    read_words(256, 1, first);
    read_words(264, 1, last);

    uint8_t req[] = {16, 3, 243, 0, 1, 2, 0xFF, 0xFF}; /* 1011, одно слово */
    uint8_t resp[8];
    assert(modbus_slave_pdu_parse(req, sizeof(req), resp, sizeof(resp), 0) == 2);
    assert(resp[0] == 0x90 && resp[1] == 3);
    assert(writes == 4 && wide[0] == 0x11223344);
    return 0;
}
"""


@unittest.skipIf(COMPILER is None, 'GCC или MSVC недоступен в этом окружении')
class TestGeneratedRuntime(unittest.TestCase):
    def test_pdu_requests_preserve_holes_ro_and_atomic_writes(self):
        self.run_model(MODEL, HARNESS)

    def test_planar_columns_with_ordinary_block_and_atomic_writes(self):
        harness = HARNESS[:HARNESS.index('int main(void)')] + PLANAR_MAIN
        self.run_model(PLANAR_MODEL, harness)

    def run_model(self, model, harness):
        library = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in (
                ('reg.yaml', model), ('device_api.h', DEVICE_API),
                ('modbus_slave_config.h', '/* Расширенная регистровая модель. */\n'),
                ('harness.c', harness),
            ):
                Path(tmp, name).write_text(content, encoding='utf-8')
            self.assertEqual(run(os.path.join(tmp, 'reg.yaml')), 0)
            proc = compile_c(tmp, [
                str(library / 'src/modbus_slave_pdu_parser.c'),
                os.path.join(tmp, 'modbus_reg_model.c'), os.path.join(tmp, 'harness.c'),
            ], [tmp, str(library / 'include'), str(library / 'src')], syntax_only=False)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            proc = subprocess.run([os.path.join(tmp, 'regmodel_test.exe')], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == '__main__':
    unittest.main()
