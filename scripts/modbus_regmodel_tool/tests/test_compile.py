"""
Сквозная проверка: генерируем .c/.h для тестовой YAML-карты, кладём рядом
заглушки библиотеки Modbus-слейва и пользовательских getter/setter,
и просим GCC или MSVC проверить синтаксис и типы.

Это самый сильный доступный тест на корректность генератора: балансировка
скобок или ручной просмотр вывода не поймают, например, несовпадение
сигнатуры обёртки с сигнатурой реального getter/setter, а компилятор поймает.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modbus_regmodel.cli import run


COMPILER = shutil.which('gcc') or shutil.which('cl')


def compile_c(tmp, sources, include_dirs, *, syntax_only):
    if os.path.basename(COMPILER).lower() in ('cl', 'cl.exe'):
        args = [COMPILER, '/nologo', '/std:c11', '/utf-8']
        args += ['/W4', '/WX', '/Zs'] if syntax_only else ['/W3', '/Fe:regmodel_test.exe']
        args += ['/I' + path for path in include_dirs]
    else:
        args = [COMPILER, '-std=c11', '-Wall', '-Wextra']
        args += ['-Werror', '-fsyntax-only'] if syntax_only else ['-o', 'regmodel_test.exe']
        for path in include_dirs:
            args += ['-I', path]
    return subprocess.run(args + sources, cwd=tmp, capture_output=True, text=True, errors='replace')

TEST_YAML = """\
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

  - addr: 0x0003
    name: ERROR_CODE
    type: int16
    getter: get_error_code

  - addr: 0x0010
    name: IGNITION_STATE
    type: uint8
    count: 3
    getter: ign_get_state
    setter: ign_set_state

  - addr: 0x0020
    name: SUPPLY_TEMP
    type: float
    getter: get_supply_temperature

  - addr: 0x0022
    name: TOTAL_CYCLES
    type: uint32
    getter: get_total_cycles
    setter: set_total_cycles

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

      - name: ENABLED
        type: bool
        getter: ch_get_enabled
        setter: ch_set_enabled
"""

# Заглушка библиотеки Modbus-слейва - в точности повторяет прототипы,
# заданные пользователем в исходном .c-файле обработчика.
PUBLIC_API_H = """\
#ifndef PUBLIC_API_STUB_H
#define PUBLIC_API_STUB_H

#include <stdint.h>
#include <stdbool.h>

typedef struct modbus_slave_context_s modbus_slave_context_t;

typedef void (*modbus_slave_holding_reg_callback_t)(uint16_t reg, modbus_slave_context_t *context);

void modbus_slave_set_write_holding_reg_callback(modbus_slave_holding_reg_callback_t cb);
void modbus_slave_set_read_holding_reg_callback(modbus_slave_holding_reg_callback_t cb);

bool modbus_slave_write_holding_reg32(modbus_slave_context_t *context, void *value);
bool modbus_slave_write_holding_reg16(modbus_slave_context_t *context, void *value);
bool modbus_slave_write_holding_reg8(modbus_slave_context_t *context, void *value);

void modbus_slave_read_holding_reg32(modbus_slave_context_t *context, void *value);
void modbus_slave_read_holding_reg16(modbus_slave_context_t *context, void *value);
void modbus_slave_read_holding_reg8(modbus_slave_context_t *context, void *value);

#endif
"""

# Заглушка пользовательских getter/setter - сигнатуры ровно такие, каких
# требует спецификация формата для каждой комбинации (скаляр/массив/блок).
SENSOR_API_H = """\
#ifndef SENSOR_API_STUB_H
#define SENSOR_API_STUB_H

#include <stdint.h>
#include <stdbool.h>

uint16_t get_system_status(void);

bool get_device_enabled(void);
void set_device_enabled(bool value);

int16_t get_error_code(void);

uint8_t ign_get_state(uint16_t index);
void ign_set_state(uint16_t index, uint8_t value);

float get_supply_temperature(void);

uint32_t get_total_cycles(void);
void set_total_cycles(uint32_t value);

float ch_get_temp(uint16_t instance);

float ch_get_setpoint_history(uint16_t instance, uint16_t elem);
void ch_set_setpoint_history(uint16_t instance, uint16_t elem, float value);

bool ch_get_enabled(uint16_t instance);
void ch_set_enabled(uint16_t instance, bool value);

#endif
"""


@unittest.skipIf(COMPILER is None, "GCC или MSVC недоступен в этом окружении")
class TestGeneratedCCompiles(unittest.TestCase):
    def test_generated_c_passes_syntax_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = os.path.join(tmp, "reg.yaml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                f.write(TEST_YAML)

            rc = run(yaml_path, dry_run=False)
            self.assertEqual(rc, 0)

            c_path = os.path.join(tmp, "modbus_reg_model.c")
            h_path = os.path.join(tmp, "modbus_reg_model.h")
            self.assertTrue(os.path.isfile(c_path))
            self.assertTrue(os.path.isfile(h_path))

            os.makedirs(os.path.join(tmp, "ModbusSlave"), exist_ok=True)
            with open(os.path.join(tmp, "ModbusSlave", "public-api.h"), "w", encoding="utf-8") as f:
                f.write(PUBLIC_API_H)
            with open(os.path.join(tmp, "sensor_api.h"), "w", encoding="utf-8") as f:
                # в YAML этого теста нет includes: секции - подключаем стаб
                # напрямую как соседний заголовок для сборки
                f.write(SENSOR_API_H)

            # Добавим #include "sensor_api.h" вручную для теста компиляции,
            # так как в TEST_YAML сознательно не заполнено поле includes -
            # это отдельная от includes проверка на совпадение сигнатур.
            with open(c_path, "r", encoding="utf-8") as f:
                src = f.read()
            src = src.replace(
                '#include "ModbusSlave/public-api.h"',
                '#include "ModbusSlave/public-api.h"\n#include "sensor_api.h"',
                1,
            )
            with open(c_path, "w", encoding="utf-8") as f:
                f.write(src)

            proc = compile_c(tmp, [c_path], [tmp], syntax_only=True)
            self.assertEqual(
                proc.returncode, 0,
                msg=f"Компилятор не прошёл проверку синтаксиса/типов:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
