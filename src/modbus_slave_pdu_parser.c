#include "ModbusSlave/public-api.h"
#include "inc/modbus_slave_pdu_parser.h"
#include "modbus_slave_config.h"

#define EXCEPT_ILLEGAL_FUNCTION 0x01
#define EXCEPT_ILLEGAL_DATA_ADDRESS 0x02
#define EXCEPT_ILLEGAL_DATA_VALUE 0x03

#define FC_READ_HOLDING_REGISTER 0x03
#define FC_WRITE_SINGLE_REGISTER 0x06
#define FC_WRITE_MULTIPLE_REGISTERS 0x10

////////////////////////////////////////////////////////////////////////////////

static modbus_slave_write_holding_reg_callback_t write_holding_reg_callback = 0;
static modbus_slave_read_holding_reg_callback_t read_holding_reg_callback = 0;

////////////////////////////////////////////////////////////////////////////////

static uint16_t make_exception_response(uint8_t *pdu_resp,
                                        uint16_t pdu_resp_size,
                                        uint8_t function_code,
                                        uint8_t exception_code)
{
  if (pdu_resp_size < 2)
    return 0;

  pdu_resp[0] = function_code | 0x80; // Устанавливаем старший бит (Error Flag)
  pdu_resp[1] = exception_code;       // Код исключения

  return 2;
}

////////////////////////////////////////////////////////////////////////////////

static uint16_t read_holding_registers(uint8_t *pdu_req,
                                       uint16_t pdu_req_size,
                                       uint8_t *pdu_resp,
                                       uint16_t pdu_resp_size,
                                       uint8_t is_broadcast)
{
  // Не отвечаем на широковещательные запросы
  if (is_broadcast)
    return 0;

  if (pdu_req_size != 5) // func_code(1) + start_reg(2) + reg_count(2)
  {
    return make_exception_response(
        pdu_resp,
        pdu_resp_size,
        FC_READ_HOLDING_REGISTER,
        EXCEPT_ILLEGAL_DATA_VALUE);
  }

  uint16_t start_reg = (pdu_req[1] << 8) | pdu_req[2];
  uint16_t reg_count = (pdu_req[3] << 8) | pdu_req[4];

  // Максимальное число запрашиваемых регистров
  // функцией 03h по спецификации 125 регистров
  if (reg_count == 0 || reg_count > 125)
  {
    return make_exception_response(
        pdu_resp,
        pdu_resp_size,
        FC_READ_HOLDING_REGISTER,
        EXCEPT_ILLEGAL_DATA_VALUE);
  }

  // Если выходим за разрешенный диапазон
  if (((uint32_t)start_reg + (uint32_t)reg_count - 1U) > 0xFFFF)
  {
    return make_exception_response(
        pdu_resp,
        pdu_resp_size,
        FC_READ_HOLDING_REGISTER,
        EXCEPT_ILLEGAL_DATA_ADDRESS);
  }

  uint16_t data_len = reg_count * 2;    // Количесто отправляемых данных
  uint16_t resp_len = data_len + 1 + 1; // data_len + func_code(1) + byte_count(1)

  if (resp_len > pdu_resp_size)
    return 0;

  uint8_t *out = pdu_resp;

  // Заполняем ответ
  (*out++) = FC_READ_HOLDING_REGISTER; // func_code(1), Read Holding Registers
  (*out++) = (uint8_t)data_len;        // byte_count(1)

#if defined(MODBUS_SLAVE_CFG_REGMODEL_SIMPLE)

  for (uint16_t i = 0; i < reg_count; i++)
  {
    uint16_t reg_value = 0;

    if (read_holding_reg_callback != 0)
      reg_value = read_holding_reg_callback(i + start_reg);

    (*out++) = (uint8_t)(reg_value >> 8); // Register value Hi
    (*out++) = (uint8_t)reg_value;        // Register value Lo
  }

#else

#error The advanced register model has not yet been implemented.

#endif

  return resp_len;
}

static uint16_t write_single_register(uint8_t *pdu_req,
                                      uint16_t pdu_req_size,
                                      uint8_t *pdu_resp,
                                      uint16_t pdu_resp_size,
                                      uint8_t is_broadcast)
{
  if (pdu_req_size != 5) // func_code(1) + reg_addr(2) + reg_value(2)
  {
    if (is_broadcast)
      return 0; // не отвечаем на широковещательный битый запрос

    return make_exception_response(
        pdu_resp,
        pdu_resp_size,
        FC_WRITE_SINGLE_REGISTER,
        EXCEPT_ILLEGAL_DATA_VALUE);
  }

  uint16_t reg_addr = ((uint16_t)pdu_req[1] << 8) | pdu_req[2];
  uint16_t reg_value = ((uint16_t)pdu_req[3] << 8) | pdu_req[4];

#if defined(MODBUS_SLAVE_CFG_REGMODEL_SIMPLE)

  if (write_holding_reg_callback != 0)
    write_holding_reg_callback(reg_addr, reg_value);

#else

#error The advanced register model has not yet been implemented.

#endif

  // Для broadcast ответа быть не должно
  if (is_broadcast)
    return 0;

  // По спецификации, ответ это точная копия запроса
  if (pdu_resp_size < 5) // func_code(1) + reg_addr(2) + reg_value(2)
    return 0;

  // Заполняем ответ

  uint8_t *out = pdu_resp;

  (*out++) = FC_WRITE_SINGLE_REGISTER; // func_code

  // Зеркальный ответ
  (*out++) = pdu_req[1]; // addr hi
  (*out++) = pdu_req[2]; // addr lo
  (*out++) = pdu_req[3]; // value hi
  (*out++) = pdu_req[4]; // value lo

  return 5; // func_code(1) + reg_addr(2) + reg_value(2)
}

static uint16_t write_multiple_registers(uint8_t *pdu_req,
                                         uint16_t pdu_req_size,
                                         uint8_t *pdu_resp,
                                         uint16_t pdu_resp_size,
                                         uint8_t is_broadcast)
{
  // func_code(1) + start_reg(2) + reg_count(2) + byte_cnt(1)
  if (pdu_req_size < 6)
  {
    if (is_broadcast)
      return 0; // не отвечаем на широковещательный битый запрос

    return make_exception_response(
        pdu_resp,
        pdu_resp_size,
        FC_WRITE_MULTIPLE_REGISTERS,
        EXCEPT_ILLEGAL_DATA_VALUE);
  }

  uint16_t start_reg = (pdu_req[1] << 8) | pdu_req[2];
  uint16_t reg_count = (pdu_req[3] << 8) | pdu_req[4];
  uint8_t byte_count = pdu_req[5];

  // Проверка количества регистров
  // Максимальное число устанавливаемых регистров
  // функцией 10h по спецификации 123 регистра
  if (reg_count == 0 || reg_count > 123)
  {
    if (is_broadcast)
      return 0;

    return make_exception_response(
        pdu_resp,
        pdu_resp_size,
        FC_WRITE_MULTIPLE_REGISTERS,
        EXCEPT_ILLEGAL_DATA_VALUE);
  }

  // Если выходим за разрешенный диапазон адресов
  if (((uint32_t)start_reg + (uint32_t)reg_count - 1U) > 0xFFFF)
  {
    if (is_broadcast)
      return 0;

    return make_exception_response(
        pdu_resp,
        pdu_resp_size,
        FC_WRITE_MULTIPLE_REGISTERS,
        EXCEPT_ILLEGAL_DATA_ADDRESS);
  }

  // Проверяем соответствие byte_count полю reg_count
  if (byte_count != (reg_count * 2))
  {
    if (is_broadcast)
      return 0;

    return make_exception_response(
        pdu_resp,
        pdu_resp_size,
        FC_WRITE_MULTIPLE_REGISTERS,
        EXCEPT_ILLEGAL_DATA_VALUE);
  }

  // func_code(1) + start_reg(2) + reg_count(2) + byte_cnt(1)
  if ((byte_count + 6) > pdu_req_size)
  {
    if (is_broadcast)
      return 0;

    return make_exception_response(
        pdu_resp,
        pdu_resp_size,
        FC_WRITE_MULTIPLE_REGISTERS,
        EXCEPT_ILLEGAL_DATA_VALUE);
  }

  uint8_t *in = pdu_req + 6;

  // Write each register

#if defined(MODBUS_SLAVE_CFG_REGMODEL_SIMPLE)

  for (uint16_t i = 0; i < reg_count; i++)
  {
    uint16_t reg_value;
    reg_value = (uint16_t)((*in++) << 8);
    reg_value |= (uint16_t)(*in++);

    if (write_holding_reg_callback)
      write_holding_reg_callback(i + start_reg, reg_value);
  }

#else

#error The advanced register model has not yet been implemented.

#endif

  // Для broadcast ответа быть не должно
  if (is_broadcast)
    return 0;

  // По спецификации, ответ это заголовок запроса, без byte_count
  if (pdu_resp_size < 5) // func_code(1) + reg_addr(2) + reg_count(2)
    return 0;

  // Заполняем ответ

  uint8_t *out = pdu_resp;

  (*out++) = FC_WRITE_MULTIPLE_REGISTERS; // func_code

  // Заголовок запроса, без byte_count
  (*out++) = pdu_req[1]; // reg_addr hi
  (*out++) = pdu_req[2]; // reg_addr lo
  (*out++) = pdu_req[3]; // reg_count hi
  (*out++) = pdu_req[4]; // reg_count lo

  return 5; // func_code(1) + start_reg(2) + reg_count(2)
}

////////////////////////////////////////////////////////////////////////////////

// Парсер PDU для слейва
// request: буфер PDU-запроса (fc + data)
// size: длина PDU-запроса
// response: буфер для записи PDU-ответа
// is_broadcast: флаг, что запрос широковещательный (не генерировать ответ, но обработать если нужно)
// Возвращает: длину PDU-ответа или 0 — если ошибка или не нужно отвечать
// Здесь реализуем базовую логику: проверка функции, генерация ответа или исключения
// Для примера поддержим функцию 0x03 (Read Holding Registers) и 0x06 (Write Single Register)
// В реальности добавьте больше функций и реальные данные (регистры)
uint16_t modbus_slave_pdu_parse(uint8_t *request,
                                uint16_t request_size,
                                uint8_t *response,
                                uint16_t response_size,
                                uint8_t is_broadcast)
{
  if (request_size < 1)
    return 0; // Нет даже function code

  uint8_t fc = request[0];

  switch (fc)
  {
  case 0x03: // Read Holding Registers
    return read_holding_registers(request, request_size, response, response_size, is_broadcast);

  case 0x06: // Preset Single Register
    return write_single_register(request, request_size, response, response_size, is_broadcast);

  case 0x10: // Preset Multiple Registers
    return write_multiple_registers(request, request_size, response, response_size, is_broadcast);

  default: // Unsupported function
    return make_exception_response(response, response_size, fc, EXCEPT_ILLEGAL_FUNCTION);
  }
}

////////////////////////////////////////////////////////////////////////////////

#if defined(MODBUS_SLAVE_CFG_REGMODEL_SIMPLE)

void modbus_slave_set_write_holding_reg_callback(modbus_slave_write_holding_reg_callback_t cb)
{
  write_holding_reg_callback = cb;
}

void modbus_slave_set_read_holding_reg_callback(modbus_slave_read_holding_reg_callback_t cb)
{
  read_holding_reg_callback = cb;
}

#else

#error The advanced register model has not yet been implemented.

#endif