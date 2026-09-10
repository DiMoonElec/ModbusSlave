# modbus-regmodel

Генератор диспетчера Modbus holding-регистров (`modbus_reg_model.c` / `.h`)
и человекочитаемой документации (`.md`) из YAML-спецификации регистровой
карты устройства.

## Использование

```bash
python generate.py path/to/regmodel.yaml
python generate.py path/to/regmodel.yaml --dry-run   # только проверить, ничего не писать
```

Пути к выходным файлам задаются в YAML (необязательно) относительно
расположения самого YAML-файла и поддерживают выход на уровень выше через `..`:

```yaml
output:
  header: "../source/modbus_reg_model.h"
  source: "../source/modbus_reg_model.c"
  docs: "../docs/regmodel.md"
```

Если `output` (или отдельные его поля) не указаны - соответствующие файлы
кладутся рядом с YAML под именами по умолчанию: `modbus_reg_model.h`,
`modbus_reg_model.c`, `modbus_reg_model.md`.

## Структура

- `modbus_regmodel/types.py`    - canonical-типы, таблицы размеров, `WrapperKey`
- `modbus_regmodel/paths.py`    - разрешение путей вывода (.h/.c/.md)
- `modbus_regmodel/model.py`    - разбор YAML, логическая и плоская модели, структурные проверки
- `modbus_regmodel/validate.py` - перекрёстные проверки (уникальность имён, пересечения адресов)
- `modbus_regmodel/codegen.py`  - генерация .h/.c
- `modbus_regmodel/docgen.py`   - генерация .md (документация по регистровой карте)
- `modbus_regmodel/cli.py`      - точка входа

## Тесты

```bash
python -m unittest discover -s tests -v
```

- `tests/test_generator.py` - разбор YAML, валидация, кодогенерация .c/.h, пути вывода
- `tests/test_docgen.py`    - генерация markdown-документации
- `tests/test_compile.py`   - сквозной тест: сгенерированный `.c` реально
  компилируется через `gcc -fsyntax-only` с заглушками библиотеки
  Modbus-слейва и пользовательских getter/setter
