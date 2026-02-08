#include "ModbusSlave/public-api.h"
#include "inc/modbus_slave_pdu_parser.h"

uint16_t modbus_slave_ethernet_parse(uint8_t *request,
                                     uint16_t request_len,
                                     uint8_t *response,
                                     uint16_t resp_size)
{
  /* Минимальная MBAP + PDU(1) = 7 + 1 = 8 */
  if (!request || !response)
    return 0;
  if (request_len < 8)
    return 0; /* минимум: MBAP(7) + 1 байт PDU */
  if (resp_size < 8)
    return 0; /* резервируем минимум для ответа */

  /* Length (4..5), Unit ID (6) */
  uint16_t length = ((uint16_t)request[4] << 8) | (uint16_t)request[5];
  uint8_t unit_id = request[6];

  /* Protocol ID (2..3) must be 0 for Modbus TCP */
  if (request[2] != 0 || request[3] != 0)
    return 0;

  /* Length must be at least 1 (Unit ID) */
  if (length < 1)
    return 0;

  /* Full frame must match length field: full = 6 + length */
  if ((uint32_t)request_len != (uint32_t)6 + (uint32_t)length)
    return 0;

  /* PDU starts at byte 7, PDU length = length - 1 (Unit ID consumed) */
  uint8_t *pdu_request = request + 7;
  uint16_t pdu_len = length - 1;

  /* Space for PDU response: resp_size - MBAP(7) */
  uint8_t *pdu_response = response + 7;
  uint16_t pdu_response_size = (resp_size >= 7) ? (uint16_t)(resp_size - 7) : 0;

  /* dispatch to PDU parser (same signature as for RTU) */
  uint16_t pdu_resp_len = modbus_slave_pdu_parse(
      pdu_request,
      pdu_len,
      pdu_response,
      pdu_response_size,
      0);

  /* If no response or broadcast, nothing to send */
  if (!pdu_resp_len)
    return 0;

  /* Check we have enough room for MBAP + PDU response */
  if ((uint32_t)7 + (uint32_t)pdu_resp_len > (uint32_t)resp_size)
    return 0;

  /* Copy Transaction ID (bytes 0..1) from request */
  response[0] = request[0]; /* trans id hi */
  response[1] = request[1]; /* trans id lo */
  
  /* Protocol ID (2..3) must be 0 for Modbus TCP */
  response[2] = 0;          /* proto id hi */
  response[3] = 0;          /* proto id lo */

  /* Length field = UnitID(1) + PDU length */
  uint16_t resp_length_field = (uint16_t)(pdu_resp_len + 1);
  response[4] = (uint8_t)(resp_length_field >> 8);
  response[5] = (uint8_t)(resp_length_field & 0xFF);

  /* Unit ID */
  response[6] = unit_id;

  /* PDU already written at response+7 by modbus_pdu_parse */
  /* return total bytes in TCP ADU */
  return (uint16_t)(7 + pdu_resp_len);
}
