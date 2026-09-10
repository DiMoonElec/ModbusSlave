# Спецификация YAML-модели регистров Modbus

## 1. Структура верхнего уровня
Файл должен содержать хотя бы один из разделов: `registers` или `blocks`.
```yaml
includes: ["header1.h", "header2.h"] # Опционально. C-заголовки для генерации.
output:                              # Опционально. Пути для генерации.
  header: "path/to/model.h"
  source: "path/to/model.c"
  docs: "path/to/docs.md"
registers: [...]                     # Список обычных регистров.
blocks: [...]                        # Список повторяющихся групп (блоков).
```

## 2. Типы данных и размер в регистрах
Modbus-регистр = 16 бит. 64-битные типы не поддерживаются. Порядок байт/слов определяется C-библиотекой.
| Canonical | Aliases | Размер (рег.) | Примечание |
| :--- | :--- | :---: | :--- |
| `bool` | `boolean` | 1 | `0` = false, `!=0` = true. |
| `uint8_t` | `uint8`, `uchar`, `byte` | 1 | |
| `int8_t` | `int8`, `char`, `sbyte` | 1 | |
| `uint16_t` | `uint16`, `ushort` | 1 | |
| `int16_t` | `int16`, `short` | 1 | |
| `uint32_t` | `uint32`, `uint` | 2 | Занимает `addr` и `addr+1`. |
| `int32_t` | `int32`, `int` | 2 | Занимает `addr` и `addr+1`. |
| `float` | - | 2 | Занимает `addr` и `addr+1`. |

## 3. Сущности и поля
### Обычный регистр
*   **`addr`** (обяз.): Адрес (hex `0x...` или dec). Диапазон `0x0000..0xFFFF`.
*   **`type`** (обяз.): Тип из таблицы выше.
*   **`name`** (опц.): Символьное имя. Regex: `^[A-Z0-9_]+$`.
*   **`count`** (опц.): Кол-во *элементов* (не регистров!). Занимаемый объем = `count * size(type)`.
*   **`getter` / `setter`** (опц.): Имена C-функций. Определяют доступ: только getter (RO), только setter (WO), оба (RW), ни одного (Reserved/пустышка).
*   **`description`**, **`unit`** (опц.): Для генерации документации.

### Блок (Повторяющаяся группа)
*   **`name`** (обяз.): Имя блока.
*   **`start_addr`** (обяз.): Адрес первого экземпляра.
*   **`repeat`** (обяз.): Кол-во экземпляров блока.
*   **`step`** (обяз.): Шаг (в регистрах) между началами экземпляров.
*   **`registers`** (обяз.): Список регистров внутри блока.

### Регистр внутри блока
Аналогичен обычному регистру, но вместо `addr` используется:
*   **`offset`** (обяз.): Смещение внутри одного экземпляра блока.
*   *Ограничение:* `offset + (count * size(type)) <= step`.

## 4. Логика адресации и прототипы C-функций
**Адресация:**
*   Обычный: `addr + elem_index * size(type)`
*   Блок: `start_addr + instance * step + offset + elem_index * size(type)`

**Прототипы (T = canonical type):**
| Контекст | Getter | Setter |
| :--- | :--- | :--- |
| Одиночный регистр | `T getter(void);` | `void setter(T value);` |
| Регистр + `count` | `T getter(uint16_t index);` | `void setter(uint16_t index, T value);` |
| Регистр в блоке | `T getter(uint16_t instance);` | `void setter(uint16_t instance, T value);` |
| Регистр в блоке + `count`| `T getter(uint16_t inst, uint16_t idx);`| `void setter(uint16_t inst, uint16_t idx, T val);`|

## 5. Строгие правила валидации
1.  **Пересечения:** Запрещено любое перекрытие диапазонов адресов (между регистрами, блоками, экземплярами блоков) с учетом `count` и размера типа.
2.  **Границы:** Максимальный занимаемый адрес (включая последний экземпляр блока) не должен превышать `0xFFFF`.
3.  **Пустота:** Файл без `registers` и `blocks` невалиден.
4.  **Уникальность:** `name` должен быть уникальным в рамках файла (на уровне логики генератора).

---

## 6. Минимальные примеры

**Пример 1: Простые регистры и output**
```yaml
output:
  header: "inc/modbus_map.h"
  source: "src/modbus_map.c"
  docs: "docs/modbus.md"
includes: ["device_api.h"]
registers:
  - addr: 0x0001
    name: STATUS
    type: uint16
    getter: get_status
  - addr: 0x0002
    type: bool          # name опущен
    getter: get_en
    setter: set_en
  - addr: 0x0010
    name: ARRAY
    type: float
    count: 4            # Займет 8 регистров (0x0010..0x0017)
    getter: get_arr
```

**Пример 2: Блоки и резервирование**
```yaml
registers:
  - addr: 0x0050
    name: RESERVED
    type: uint16
    count: 10           # Зарезервировано (нет getter/setter)
blocks:
  - name: CHANNEL
    start_addr: 0x0100
    repeat: 3
    step: 0x10          # Шаг 16 регистров
    registers:
      - offset: 0x00
        name: TEMP
        type: float     # Займет 2 регистра
        getter: ch_get_temp
      - offset: 0x04
        name: COEFFS
        type: int16
        count: 3        # Займет 3 регистра (0x04, 0x05, 0x06)
        getter: ch_get_k
        setter: ch_set_k
```