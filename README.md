# Библиотека протокола Modbus Slave

## Описание

Данная библиотека реализует парсер протоколов:

- Modbus RTU
- Modbus TCP

Библиотека написана на C и разрабатывается с упором на легковесность и нетребовательность к ресурсам. Это особенно актуально для использования во встраиваемых решениях с ограниченным объёмом ресурсов.

## Файлы библиотеки

- ```include\ModbusSlave\public-api.h``` - API-функции, доступные пользователю
- ```src\``` - исходники на языке C
- ```templates\``` - шаблоны конфигурационных файлов

## Использование

Пример кода работы с библиотекой.  

**ВНИМАНИЕ!!!** Все функции библиотеки желательно вызывать из основного потока; не рекомендуется вызывать функции библиотеки из прерываний.

Если всё-таки хотите вызывать функции ```modbus_slave_rtu_parse()``` и ```modbus_slave_ethernet_parse()``` из прерывания, изучите исходный код повнимательнее, чтобы всё сделать правильно :)

```c
#include "ModbusSlave/public-api.h"

// Переменные, в которых хранятся значения Modbus-регистров
static uint16_t device_reg_0;
static uint16_t device_reg_1;
static uint16_t device_reg_2;
static uint16_t device_reg_3;

// Callback установки значения регистра
static void RegModelWriteHoldingReg(uint16_t reg, uint16_t value)
{
  switch (reg)
  {
  case 0:
    device_reg_0 = value;
    break;

  case 1:
    device_reg_1 = value;
    break;

  case 2:
    device_reg_2 = value;
    break;

  case 3:
    device_reg_3 = value;
    break;
  }
}

// Callback чтения значения регистра
static uint16_t RegModelReadHoldingReg(uint16_t reg)
{
  switch (reg)
  {
  case 0:
    return device_reg_0;
  case 1:
    return device_reg_1;
  case 2:
    return device_reg_2;
  case 3:
    return device_reg_3;
  }

  return 0; // Несуществующий регистр читается как 0
}

// Инициализация библиотеки 
void Init(void)
{
  // Устанавливаем адрес для Modbus RTU
  modbus_slave_rtu_set_slave_address(21);

  // Устанавливаем callback-функции записи/чтения регистров.
  // Эти callback будут вызываться при получении
  // соответствующего запроса через Modbus
  modbus_slave_set_write_holding_reg_callback(RegModelWriteHoldingReg);
  modbus_slave_set_read_holding_reg_callback(RegModelReadHoldingReg);
}

// Псевдокод функции обмена данными по RS485
void rs485(void)
{
  uint8_t buffer[1024];
  uint16_t rx_size;

  while (1)
  {
    /*
      Получаем пакет по RS485 в buffer,
      в rx_size — количество полученных байт
    */
    rx_size = rs485_receive(buffer);

    uint16_t resp_size = modbus_slave_rtu_parse(
        buffer,  // Запрос
        rx_size, // Длина запроса
        buffer,  // Сюда будет записан ответ, можно использовать один и тот же буфер
        1024     // Размер буфера ответа
    );

    if (resp_size != 0) // Если библиотека сформировала ответ
    {
      // Отправляем ответ
      rs485_transmit(buffer, resp_size);
    }
  }
}

// Псевдокод функции обмена данными по TCP/IP
void Ethernet(void)
{
  uint8_t buffer[1024];
  uint16_t rx_size;

  while (1)
  {
    /*
      Получаем пакет из TCP-сокета в buffer,
      в rx_size — количество полученных байт
    */
    rx_size = tcp_receive_pack(buffer);

    uint16_t resp_size = modbus_slave_ethernet_parse(
        buffer,  // Запрос
        rx_size, // Длина запроса
        buffer,  // Сюда будет записан ответ, можно использовать один и тот же буфер
        1024     // Размер буфера ответа
    );

    if (resp_size != 0) // Если библиотека сформировала ответ
    {
      // Отправляем ответ в TCP-сокет
      tcp_transmit_pack(buffer, resp_size);
    }
  }
}

```

## Подключение к проекту

- Размещаем библиотеку в исходниках проекта, например, в ```ModbusSlave\```
- Подключаем к проекту каталог ```ModbusSlave\include\```
- Из ```ModbusSlave\templates``` копируем файл ```modbus_slave_config.h``` в каталог проекта с h-файлами
- Добавляем в проект все .c-файлы из каталога ```ModbusSlave\src```

В файле ```modbus_slave_config.h``` находится конфигурация библиотеки:

```c
/*
 * Уберите комментарий у #define MODBUS_SLAVE_CFG_RTU_DISABLE_ADR_CHECK,
 * если хотите, чтобы Modbus RTU адрес слейва игнорировался.
 * Это удобно, если на шине только одно устройство.
 */
// #define MODBUS_SLAVE_CFG_RTU_DISABLE_ADR_CHECK

/*
 * На данный момент этот #define должен быть всегда определён.
 * В дальнейшем планируется расширение конфигурации.
 */
#define MODBUS_SLAVE_CFG_REGMODEL_SIMPLE

```