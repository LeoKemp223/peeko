/**
 * @file peeko.h
 * @brief Peeko MCU Library - Serial communication library for RAM read/write
 *
 * This library provides MCU-side support for the Peeko tool.
 * It only depends on UART RX/TX interrupt functions.
 *
 * Usage:
 * 1. Call pk_init() with your UART send function
 * 2. Call pk_rx_byte() from UART RX interrupt
 * 3. Call pk_tx_complete() from UART TX complete interrupt
 *
 * Example:
 * @code
 * void uart_send_byte(uint8_t byte) {
 *     UART_DATA = byte;
 * }
 *
 * void UART_RX_IRQHandler(void) {
 *     uint8_t c = UART_DATA;
 *     pk_rx_byte(c);
 * }
 *
 * void UART_TX_IRQHandler(void) {
 *     pk_tx_complete();
 * }
 *
 * int main(void) {
 *     pk_init(uart_send_byte);
 *     // Enable UART interrupts
 *     while (1) { }
 * }
 * @endcode
 */

#ifndef PEEKO_H
#define PEEKO_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*===========================================================================*/
/* Configuration                                                             */
/*===========================================================================*/

/**
 * @brief Maximum payload size in bytes
 * Adjust based on available RAM. Default: 256 bytes.
 * Keep this small for MCU RAM/stack safety; applications may use this macro
 * for local buffers in addition to the static buffers used by the library.
 * Minimum recommended: 64 bytes
 */
#ifndef PK_MAX_PAYLOAD_SIZE
#define PK_MAX_PAYLOAD_SIZE     256
#endif

#if PK_MAX_PAYLOAD_SIZE > 1024
#error "PK_MAX_PAYLOAD_SIZE is too large for typical MCU RAM/stack usage"
#endif

/**
 * @brief Maximum number of variables per command
 * Default: 30 variables
 */
#ifndef PK_MAX_VARIABLES
#define PK_MAX_VARIABLES        30
#endif

/*===========================================================================*/
/* Protocol Constants                                                        */
/*===========================================================================*/

/** @brief Start of frame marker */
#define PK_SOF                  0xAA

/** @brief Frame overhead: SOF(1) + LEN(2) + CMD(1) + SEQ(1) + CRC(2) = 7 */
#define PK_FRAME_OVERHEAD       7

/*---------------------------------------------------------------------------*/
/* Command Types                                                             */
/*---------------------------------------------------------------------------*/

#define PK_CMD_READ_VAR         0x01    /**< Read variable(s) request */
#define PK_CMD_WRITE_VAR        0x02    /**< Write variable(s) request */
#define PK_CMD_READ_RESP        0x81    /**< Read response */
#define PK_CMD_WRITE_RESP       0x82    /**< Write response */
#define PK_CMD_ERROR            0xFF    /**< Error response */
#define PK_CMD_PING             0x10    /**< Heartbeat ping */
#define PK_CMD_PONG             0x90    /**< Heartbeat pong */

/*---------------------------------------------------------------------------*/
/* Error Codes                                                               */
/*---------------------------------------------------------------------------*/

#define PK_ERR_OK               0x00    /**< Success */
#define PK_ERR_CRC              0x01    /**< CRC mismatch */
#define PK_ERR_ADDR             0x02    /**< Invalid address */
#define PK_ERR_SIZE             0x03    /**< Invalid size */
#define PK_ERR_CMD              0x04    /**< Unknown command */

/*---------------------------------------------------------------------------*/
/* Bitfield Markers                                                          */
/*---------------------------------------------------------------------------*/

/** @brief Marker indicating non-bitfield variable */
#define PK_NO_BITFIELD          0xFF

/*===========================================================================*/
/* Types                                                                     */
/*===========================================================================*/

/**
 * @brief Callback function type for sending a single byte
 * @param byte The byte to send via UART
 */
typedef void (*pk_send_byte_fn)(uint8_t byte);

/*===========================================================================*/
/* Public API                                                                */
/*===========================================================================*/

/**
 * @brief Initialize Peeko library
 * @param send_fn Callback function for sending a byte via UART
 *
 * Call this function once during system initialization.
 */
void pk_init(pk_send_byte_fn send_fn);

/**
 * @brief Process received byte from UART
 * @param byte The received byte
 *
 * Call this function from UART RX interrupt handler.
 * This function is interrupt-safe and executes quickly.
 */
void pk_rx_byte(uint8_t byte);

/**
 * @brief Handle UART TX complete event
 *
 * Call this function from UART TX complete interrupt handler.
 * This triggers sending the next byte if available.
 */
void pk_tx_complete(void);

/**
 * @brief Check if transmitter is busy
 * @return true if transmission is in progress
 */
bool pk_is_tx_busy(void);

/**
 * @brief Get library version
 * @return Version string
 */
const char* pk_get_version(void);

#ifdef __cplusplus
}
#endif

#endif /* PEEKO_H */
