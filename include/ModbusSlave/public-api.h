#ifndef __MODBUS_SLAVE_PUBLIC_API_H__
#define __MODBUS_SLAVE_PUBLIC_API_H__

#include <stdint.h>
#include "modbus_slave_config.h"

#if defined(MODBUS_SLAVE_CFG_REGMODEL_SIMPLE)

typedef void (*modbus_slave_write_holding_reg_callback_t)(uint16_t reg, uint16_t value);
typedef uint16_t (*modbus_slave_read_holding_reg_callback_t)(uint16_t reg);

void modbus_slave_set_write_holding_reg_callback(modbus_slave_write_holding_reg_callback_t cb);
void modbus_slave_set_read_holding_reg_callback(modbus_slave_read_holding_reg_callback_t cb);

#else

#error The advanced register model has not yet been implemented.

#endif

#if !defined(MODBUS_SLAVE_RTU_DISABLE_ADR_CHECK)

void modbus_slave_rtu_set_slave_address(uint8_t addr);
uint8_t modbus_slave_rtu_get_slave_address(void);

#endif

uint16_t modbus_slave_rtu_parse(uint8_t *request,
                                uint16_t request_len,
                                uint8_t *response,
                                uint16_t resp_size);

uint16_t modbus_slave_ethernet_parse(uint8_t *request,
                                     uint16_t request_len,
                                     uint8_t *response,
                                     uint16_t resp_size);

#endif