#ifndef __MODBUS_SLAVE_PDU_PARSER_H__
#define __MODBUS_SLAVE_PDU_PARSER_H__

#include <stdint.h>

uint16_t modbus_slave_pdu_parse(uint8_t *request,
                                uint16_t request_size,
                                uint8_t *response,
                                uint16_t response_size,
                                uint8_t is_broadcast);

#endif