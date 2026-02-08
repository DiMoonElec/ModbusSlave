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

#endif
