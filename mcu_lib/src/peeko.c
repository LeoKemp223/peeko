/**
 * @file peeko.c
 * @brief Peeko MCU Library Implementation
 *
 * Communication protocol implementation for RAM read/write operations.
 * Uses state machine for receiving frames and interrupt-driven transmission.
 */

#include "peeko.h"
#include <string.h>

/*===========================================================================*/
/* Version                                                                   */
/*===========================================================================*/

#define PK_VERSION_STRING   "1.0.0"

/*===========================================================================*/
/* Private Types                                                             */
/*===========================================================================*/

/** @brief Receiver state machine states */
typedef enum {
    RX_STATE_IDLE,          /**< Waiting for SOF */
    RX_STATE_LEN_L,         /**< Waiting for length low byte */
    RX_STATE_LEN_H,         /**< Waiting for length high byte */
    RX_STATE_CMD,           /**< Waiting for command */
    RX_STATE_SEQ,           /**< Waiting for sequence number */
    RX_STATE_PAYLOAD,       /**< Receiving payload */
    RX_STATE_CRC_L,         /**< Waiting for CRC low byte */
    RX_STATE_CRC_H          /**< Waiting for CRC high byte */
} rx_state_t;

/** @brief Transmitter state */
typedef enum {
    TX_STATE_IDLE,          /**< Idle, no transmission */
    TX_STATE_SENDING        /**< Transmission in progress */
} tx_state_t;

/*===========================================================================*/
/* Private Variables                                                         */
/*===========================================================================*/

/** @brief Receive buffer */
static uint8_t pk_rx_buffer[PK_FRAME_OVERHEAD + PK_MAX_PAYLOAD_SIZE];

/** @brief Transmit buffer */
static uint8_t pk_tx_buffer[PK_FRAME_OVERHEAD + PK_MAX_PAYLOAD_SIZE];

/** @brief Receiver state */
static volatile rx_state_t pk_rx_state = RX_STATE_IDLE;

/** @brief Transmitter state */
static volatile tx_state_t pk_tx_state = TX_STATE_IDLE;

/** @brief Expected payload length */
static uint16_t pk_rx_payload_len;

/** @brief Current payload index */
static uint16_t pk_rx_payload_idx;

/** @brief Total TX frame length */
static uint16_t pk_tx_len;

/** @brief Current TX byte index */
static volatile uint16_t pk_tx_idx;

/** @brief Send byte callback */
static pk_send_byte_fn pk_send_byte = NULL;

/*===========================================================================*/
/* Private Function Prototypes                                               */
/*===========================================================================*/

static uint16_t pk_crc16_ccitt(const uint8_t *data, uint16_t len);
static void pk_process_frame(void);
static void pk_handle_read(const uint8_t *payload, uint16_t len, uint8_t seq);
static void pk_handle_write(const uint8_t *payload, uint16_t len, uint8_t seq);
static void pk_send_response(uint8_t cmd, uint8_t seq, uint16_t payload_len);
static void pk_send_error(uint8_t error_code, uint8_t seq);
static void pk_send_pong(uint8_t seq);

/*===========================================================================*/
/* CRC16 Implementation                                                      */
/*===========================================================================*/

/**
 * @brief Calculate CRC16-CCITT
 * @param data Input data
 * @param len Data length
 * @return CRC16 value
 *
 * Polynomial: 0x1021, Initial value: 0xFFFF
 */
static uint16_t pk_crc16_ccitt(const uint8_t *data, uint16_t len)
{
    uint16_t crc = 0xFFFF;
    uint8_t i;

    while (len--) {
        crc ^= (uint16_t)(*data++) << 8;
        for (i = 0; i < 8; i++) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

/*===========================================================================*/
/* Public Functions                                                          */
/*===========================================================================*/

void pk_init(pk_send_byte_fn send_fn)
{
    pk_send_byte = send_fn;
    pk_rx_state = RX_STATE_IDLE;
    pk_tx_state = TX_STATE_IDLE;
    pk_tx_idx = 0;
    pk_tx_len = 0;
}

void pk_rx_byte(uint8_t byte)
{
    switch (pk_rx_state) {
        case RX_STATE_IDLE:
            if (byte == PK_SOF) {
                pk_rx_buffer[0] = byte;
                pk_rx_state = RX_STATE_LEN_L;
            }
            break;

        case RX_STATE_LEN_L:
            pk_rx_buffer[1] = byte;
            pk_rx_payload_len = byte;
            pk_rx_state = RX_STATE_LEN_H;
            break;

        case RX_STATE_LEN_H:
            pk_rx_buffer[2] = byte;
            pk_rx_payload_len |= ((uint16_t)byte << 8);
            if (pk_rx_payload_len > PK_MAX_PAYLOAD_SIZE) {
                pk_rx_state = RX_STATE_IDLE;
            } else {
                pk_rx_state = RX_STATE_CMD;
            }
            break;

        case RX_STATE_CMD:
            pk_rx_buffer[3] = byte;
            pk_rx_state = RX_STATE_SEQ;
            break;

        case RX_STATE_SEQ:
            pk_rx_buffer[4] = byte;
            pk_rx_payload_idx = 0;
            if (pk_rx_payload_len > 0) {
                pk_rx_state = RX_STATE_PAYLOAD;
            } else {
                pk_rx_state = RX_STATE_CRC_L;
            }
            break;

        case RX_STATE_PAYLOAD:
            pk_rx_buffer[5 + pk_rx_payload_idx] = byte;
            pk_rx_payload_idx++;
            if (pk_rx_payload_idx >= pk_rx_payload_len) {
                pk_rx_state = RX_STATE_CRC_L;
            }
            break;

        case RX_STATE_CRC_L:
            pk_rx_buffer[5 + pk_rx_payload_len] = byte;
            pk_rx_state = RX_STATE_CRC_H;
            break;

        case RX_STATE_CRC_H:
            pk_rx_buffer[6 + pk_rx_payload_len] = byte;
            pk_process_frame();
            pk_rx_state = RX_STATE_IDLE;
            break;

        default:
            pk_rx_state = RX_STATE_IDLE;
            break;
    }
}

void pk_tx_complete(void)
{
    if (pk_tx_state == TX_STATE_SENDING && pk_tx_idx < pk_tx_len) {
        if (pk_send_byte != NULL) {
            pk_send_byte(pk_tx_buffer[pk_tx_idx]);
            pk_tx_idx++;
        }
    } else {
        pk_tx_state = TX_STATE_IDLE;
    }
}

bool pk_is_tx_busy(void)
{
    return (pk_tx_state == TX_STATE_SENDING);
}

const char* pk_get_version(void)
{
    return PK_VERSION_STRING;
}

/*===========================================================================*/
/* Private Functions                                                         */
/*===========================================================================*/

/**
 * @brief Process a complete received frame
 */
static void pk_process_frame(void)
{
    uint16_t frame_len;
    uint16_t recv_crc;
    uint16_t calc_crc;
    uint8_t cmd;
    uint8_t seq;
    uint8_t *payload;

    frame_len = 5 + pk_rx_payload_len;

    recv_crc = pk_rx_buffer[frame_len] |
               ((uint16_t)pk_rx_buffer[frame_len + 1] << 8);
    calc_crc = pk_crc16_ccitt(pk_rx_buffer, frame_len);

    if (recv_crc != calc_crc) {
        pk_send_error(PK_ERR_CRC, pk_rx_buffer[4]);
        return;
    }

    cmd = pk_rx_buffer[3];
    seq = pk_rx_buffer[4];
    payload = &pk_rx_buffer[5];

    switch (cmd) {
        case PK_CMD_READ_VAR:
            pk_handle_read(payload, pk_rx_payload_len, seq);
            break;

        case PK_CMD_WRITE_VAR:
            pk_handle_write(payload, pk_rx_payload_len, seq);
            break;

        case PK_CMD_PING:
            pk_send_pong(seq);
            break;

        default:
            pk_send_error(PK_ERR_CMD, seq);
            break;
    }
}

/**
 * @brief Handle read variable command
 * @param payload Command payload
 * @param len Payload length
 * @param seq Sequence number
 */
static void pk_handle_read(const uint8_t *payload, uint16_t len, uint8_t seq)
{
    uint8_t count;
    uint8_t i;
    uint16_t resp_len;
    uint8_t *resp;
    const uint8_t *var_entry;
    uint32_t addr;
    uint16_t size;
    uint8_t bit_off;
    uint8_t bit_size;
    uint8_t *mem_ptr;
    uint16_t j;

    if (len < 1) {
        pk_send_error(PK_ERR_SIZE, seq);
        return;
    }

    count = payload[0];
    if (count == 0 || count > PK_MAX_VARIABLES) {
        pk_send_error(PK_ERR_SIZE, seq);
        return;
    }

    if (len < (uint16_t)(1 + count * 8)) {
        pk_send_error(PK_ERR_SIZE, seq);
        return;
    }

    resp = &pk_tx_buffer[5];
    resp_len = 1;
    resp[0] = count;

    for (i = 0; i < count; i++) {
        var_entry = &payload[1 + i * 8];

        addr = var_entry[0] |
               ((uint32_t)var_entry[1] << 8) |
               ((uint32_t)var_entry[2] << 16) |
               ((uint32_t)var_entry[3] << 24);
        size = var_entry[4] | ((uint16_t)var_entry[5] << 8);
        bit_off = var_entry[6];
        bit_size = var_entry[7];

        mem_ptr = (uint8_t *)addr;

        if (bit_off != PK_NO_BITFIELD) {
            uint8_t byte_val = *mem_ptr;
            uint8_t mask = (uint8_t)((1U << bit_size) - 1U);
            uint8_t value = (byte_val >> bit_off) & mask;
            resp[resp_len] = value;
            resp_len++;
        } else {
            for (j = 0; j < size; j++) {
                if (resp_len >= PK_MAX_PAYLOAD_SIZE) {
                    pk_send_error(PK_ERR_SIZE, seq);
                    return;
                }
                resp[resp_len] = mem_ptr[j];
                resp_len++;
            }
        }
    }

    pk_send_response(PK_CMD_READ_RESP, seq, resp_len);
}

/**
 * @brief Handle write variable command
 * @param payload Command payload
 * @param len Payload length
 * @param seq Sequence number
 */
static void pk_handle_write(const uint8_t *payload, uint16_t len, uint8_t seq)
{
    uint8_t count;
    uint8_t i;
    uint16_t offset;
    uint32_t addr;
    uint16_t size;
    uint8_t bit_off;
    uint8_t bit_size;
    uint8_t *mem_ptr;
    uint16_t j;

    if (len < 1) {
        pk_send_error(PK_ERR_SIZE, seq);
        return;
    }

    count = payload[0];
    if (count == 0 || count > PK_MAX_VARIABLES) {
        pk_send_error(PK_ERR_SIZE, seq);
        return;
    }

    offset = 1;

    for (i = 0; i < count; i++) {
        if (offset + 8 > len) {
            pk_send_error(PK_ERR_SIZE, seq);
            return;
        }

        addr = payload[offset] |
               ((uint32_t)payload[offset + 1] << 8) |
               ((uint32_t)payload[offset + 2] << 16) |
               ((uint32_t)payload[offset + 3] << 24);
        size = payload[offset + 4] | ((uint16_t)payload[offset + 5] << 8);
        bit_off = payload[offset + 6];
        bit_size = payload[offset + 7];
        offset += 8;

        mem_ptr = (uint8_t *)addr;

        if (bit_off != PK_NO_BITFIELD) {
            if (offset >= len) {
                pk_send_error(PK_ERR_SIZE, seq);
                return;
            }
            uint8_t byte_val = *mem_ptr;
            uint8_t mask = (uint8_t)(((1U << bit_size) - 1U) << bit_off);
            uint8_t new_val = payload[offset];
            *mem_ptr = (byte_val & ~mask) | ((new_val << bit_off) & mask);
            offset++;
        } else {
            if (offset + size > len) {
                pk_send_error(PK_ERR_SIZE, seq);
                return;
            }
            for (j = 0; j < size; j++) {
                mem_ptr[j] = payload[offset];
                offset++;
            }
        }
    }

    pk_tx_buffer[5] = PK_ERR_OK;
    pk_send_response(PK_CMD_WRITE_RESP, seq, 1);
}

/**
 * @brief Send response frame
 * @param cmd Response command
 * @param seq Sequence number
 * @param payload_len Payload length (payload already in pk_tx_buffer[5..])
 */
static void pk_send_response(uint8_t cmd, uint8_t seq, uint16_t payload_len)
{
    uint16_t crc;

    pk_tx_buffer[0] = PK_SOF;
    pk_tx_buffer[1] = (uint8_t)(payload_len & 0xFF);
    pk_tx_buffer[2] = (uint8_t)((payload_len >> 8) & 0xFF);
    pk_tx_buffer[3] = cmd;
    pk_tx_buffer[4] = seq;

    crc = pk_crc16_ccitt(pk_tx_buffer, 5 + payload_len);
    pk_tx_buffer[5 + payload_len] = (uint8_t)(crc & 0xFF);
    pk_tx_buffer[6 + payload_len] = (uint8_t)((crc >> 8) & 0xFF);

    pk_tx_len = 7 + payload_len;
    pk_tx_idx = 1;
    pk_tx_state = TX_STATE_SENDING;

    if (pk_send_byte != NULL) {
        pk_send_byte(pk_tx_buffer[0]);
    }
}

/**
 * @brief Send error response
 * @param error_code Error code
 * @param seq Sequence number
 */
static void pk_send_error(uint8_t error_code, uint8_t seq)
{
    pk_tx_buffer[5] = error_code;
    pk_send_response(PK_CMD_ERROR, seq, 1);
}

/**
 * @brief Send pong response
 * @param seq Sequence number
 */
static void pk_send_pong(uint8_t seq)
{
    pk_send_response(PK_CMD_PONG, seq, 0);
}
