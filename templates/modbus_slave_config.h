#ifndef __MODBUS_SLAVE_CONFIG_H__
#define __MODBUS_SLAVE_CONFIG_H__

/*
 * Disable Modbus RTU slave address checking.
 *
 * If defined, the slave will process any received request
 * regardless of the slave address field.
 * Useful for single-device buses.
 */
// #define MODBUS_SLAVE_CFG_RTU_DISABLE_ADR_CHECK

/*
 * It must be defined for now
*/
#define MODBUS_SLAVE_CFG_REGMODEL_SIMPLE

/*
 * Byte order for 32-bit values stored in two consecutive Modbus registers.
 * If this option is omitted, the library uses ABCD order for backward
 * compatibility with older modbus_slave_config.h files.
 *
 * Available values:
 *   MODBUS_SLAVE_REG32_BYTE_ORDER_ABCD
 *   MODBUS_SLAVE_REG32_BYTE_ORDER_BADC
 *   MODBUS_SLAVE_REG32_BYTE_ORDER_CDAB
 *   MODBUS_SLAVE_REG32_BYTE_ORDER_DCBA
 */
// #define MODBUS_SLAVE_CFG_REG32_BYTE_ORDER MODBUS_SLAVE_REG32_BYTE_ORDER_ABCD

#endif
