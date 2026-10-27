#ifndef __MODBUS_SLAVE_PUBLIC_API_H__
#define __MODBUS_SLAVE_PUBLIC_API_H__

#include <stdint.h>
#include <stdbool.h>
#include "modbus_slave_config.h"

#if defined(MODBUS_SLAVE_CFG_REGMODEL_SIMPLE)

typedef void (*modbus_slave_write_holding_reg_callback_t)(uint16_t reg, uint16_t value);
typedef uint16_t (*modbus_slave_read_holding_reg_callback_t)(uint16_t reg);

#else

typedef struct
{
  uint8_t *buffer;
  uint16_t tail;
  uint16_t consumed;
  uint8_t state;
} modbus_slave_context_t;

typedef void (*modbus_slave_write_holding_reg_callback_t)(uint16_t reg, 
    modbus_slave_context_t *context);
typedef void (*modbus_slave_read_holding_reg_callback_t)(uint16_t reg, 
    modbus_slave_context_t *context);


/* 32-bit value byte order in two consecutive Modbus registers. */
#define MODBUS_SLAVE_REG32_BYTE_ORDER_ABCD 0
#define MODBUS_SLAVE_REG32_BYTE_ORDER_BADC 1
#define MODBUS_SLAVE_REG32_BYTE_ORDER_CDAB 2
#define MODBUS_SLAVE_REG32_BYTE_ORDER_DCBA 3

/*
 * Backward compatibility: old modbus_slave_config.h files do not define
 * MODBUS_SLAVE_CFG_REG32_BYTE_ORDER. In that case use the historical ABCD
 * order implemented by modbus_slave_*_holding_reg32().
 */
#ifndef MODBUS_SLAVE_CFG_REG32_BYTE_ORDER
#define MODBUS_SLAVE_CFG_REG32_BYTE_ORDER MODBUS_SLAVE_REG32_BYTE_ORDER_ABCD
#endif

#if (MODBUS_SLAVE_CFG_REG32_BYTE_ORDER != MODBUS_SLAVE_REG32_BYTE_ORDER_ABCD) && \
    (MODBUS_SLAVE_CFG_REG32_BYTE_ORDER != MODBUS_SLAVE_REG32_BYTE_ORDER_BADC) && \
    (MODBUS_SLAVE_CFG_REG32_BYTE_ORDER != MODBUS_SLAVE_REG32_BYTE_ORDER_CDAB) && \
    (MODBUS_SLAVE_CFG_REG32_BYTE_ORDER != MODBUS_SLAVE_REG32_BYTE_ORDER_DCBA)
#error "Invalid MODBUS_SLAVE_CFG_REG32_BYTE_ORDER value"
#endif

bool modbus_slave_write_holding_reg32_abcd(modbus_slave_context_t *context, void *value);
bool modbus_slave_write_holding_reg32_badc(modbus_slave_context_t *context, void *value);
bool modbus_slave_write_holding_reg32_cdab(modbus_slave_context_t *context, void *value);
bool modbus_slave_write_holding_reg32_dcba(modbus_slave_context_t *context, void *value);

bool modbus_slave_write_holding_reg16(modbus_slave_context_t *context, void *value);
bool modbus_slave_write_holding_reg8(modbus_slave_context_t *context, void *value);

void modbus_slave_read_holding_reg32_abcd(modbus_slave_context_t *context, void *value);
void modbus_slave_read_holding_reg32_badc(modbus_slave_context_t *context, void *value);
void modbus_slave_read_holding_reg32_cdab(modbus_slave_context_t *context, void *value);
void modbus_slave_read_holding_reg32_dcba(modbus_slave_context_t *context, void *value);

void modbus_slave_read_holding_reg16(modbus_slave_context_t *context, void *value);
void modbus_slave_read_holding_reg8(modbus_slave_context_t *context, void *value);

#if MODBUS_SLAVE_CFG_REG32_BYTE_ORDER == MODBUS_SLAVE_REG32_BYTE_ORDER_ABCD
#define modbus_slave_write_holding_reg32 modbus_slave_write_holding_reg32_abcd
#define modbus_slave_read_holding_reg32  modbus_slave_read_holding_reg32_abcd
#elif MODBUS_SLAVE_CFG_REG32_BYTE_ORDER == MODBUS_SLAVE_REG32_BYTE_ORDER_BADC
#define modbus_slave_write_holding_reg32 modbus_slave_write_holding_reg32_badc
#define modbus_slave_read_holding_reg32  modbus_slave_read_holding_reg32_badc
#elif MODBUS_SLAVE_CFG_REG32_BYTE_ORDER == MODBUS_SLAVE_REG32_BYTE_ORDER_CDAB
#define modbus_slave_write_holding_reg32 modbus_slave_write_holding_reg32_cdab
#define modbus_slave_read_holding_reg32  modbus_slave_read_holding_reg32_cdab
#else
#define modbus_slave_write_holding_reg32 modbus_slave_write_holding_reg32_dcba
#define modbus_slave_read_holding_reg32  modbus_slave_read_holding_reg32_dcba
#endif

#endif

void modbus_slave_set_write_holding_reg_callback(modbus_slave_write_holding_reg_callback_t cb);
void modbus_slave_set_read_holding_reg_callback(modbus_slave_read_holding_reg_callback_t cb);


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