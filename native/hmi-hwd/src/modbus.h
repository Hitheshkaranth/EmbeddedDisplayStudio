/*
 * modbus.h -- Modbus TCP master (CONTRACT 2.5 "mb." tags; daemon/modbus.py
 * and HwDaemon._init_modbus/_do_modbus_poll/_modbus_write are the reference).
 *
 * Two layers:
 *  - codec (pure, unit-tested in tests/test_modbus.c): MBAP + PDU framing for
 *    FC 1/2/3/4/5/6/15/16, RTU framing with CRC, typed register
 *    decode/encode with word_order;
 *  - the backend hwd_backend_modbus (modbus.c): one TCP connection and/or
 *    one RTU serial line, a poll thread per link at its poll_interval_ms
 *    reading every configured tag (grouping contiguous ranges is allowed,
 *    not required), scale/offset/enum applied, results in the tag store,
 *    reconnect every reconnect_s with backoff; sys.modbus_online and
 *    sys.modbus_rtu_online track the links.
 *
 * hwd.json "modbus" section, per tag (validated by the backend's validate()
 * with the same rules and messages as load_config in daemon/hmi_hwd.py;
 * "modbus_rtu" tags take the same keys plus "unit"):
 *   kind: coil|discrete|holding|input; address >= 0;
 *   type: bool (coil/discrete) | int16|uint16|int32|uint32|float32;
 *   scale (default 1), offset (default 0): published = raw * scale + offset;
 *   word_order: "big" (default) | "little" for 32-bit types;
 *   writable (coil/holding only), safe_state;
 *   enum: optional array of strings for holding/input integer types --
 *     published value = enum[raw] when 0 <= raw < len, else the number;
 *     a write of one of those strings writes its index. (NEW in wave 5; the
 *     Python daemon gains the same in W4.)
 *
 * Simulation: with --sim the client never opens a socket; every mb.* tag
 * reads its safe_state/0 and sys.modbus_online stays false -- unless
 * live is true (--modbus-live), which talks to the configured host even in
 * sim mode (Studio's "Test against PLC" with daemon/plc_sim.py).
 *
 * FROZEN.
 */
#ifndef HWD_MODBUS_H
#define HWD_MODBUS_H

#include "hwd.h"
#include "tagstore.h"
#include "cJSON.h"

/* ---- codec ------------------------------------------------------------ */
typedef enum { MB_COIL, MB_DISCRETE, MB_HOLDING, MB_INPUT } mb_kind;
typedef enum { MB_BOOL, MB_INT16, MB_UINT16, MB_INT32, MB_UINT32, MB_FLOAT32 } mb_type;

/* Registers a type occupies (bool: 1 bit, 16-bit: 1, 32-bit: 2). */
int mb_type_registers(mb_type t);
/* Decode regs[0..] (host order uint16 as on the wire, big-endian words) into
 * a number, honouring word_order ("little" swaps the two words). */
double mb_decode(mb_type t, const uint16_t *regs, bool little_words);
/* Encode a number (already un-scaled to raw) into regs; returns registers. */
int mb_encode(mb_type t, double raw, uint16_t *regs, bool little_words);

/* Build a request ADU (MBAP + PDU) into buf; returns its length. */
size_t mb_req_read(uint8_t *buf, uint16_t tid, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t count);
size_t mb_req_write_single(uint8_t *buf, uint16_t tid, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t value);
size_t mb_req_write_multi(uint8_t *buf, uint16_t tid, uint8_t unit, uint16_t addr, const uint16_t *regs, uint16_t count);
/* Parse a response ADU for a read: fills bits (FC1/2, one byte per bit) or
 * regs (FC3/4). Returns 0 on success, the exception code (1..255) for a
 * Modbus exception, -1 for a malformed/short/mismatched frame. */
int mb_parse_read(const uint8_t *buf, size_t len, uint16_t tid, uint8_t fc,
                  uint16_t count, uint8_t *bits, uint16_t *regs);
/* Parse a write echo (FC5/6/15/16): 0 ok, exception code, or -1. */
int mb_parse_write(const uint8_t *buf, size_t len, uint16_t tid, uint8_t fc);

/* ---- RTU ---------------------------------------------------------------- */
/* CRC-16/MODBUS (poly 0xA001, init 0xFFFF) over buf[0..len). */
uint16_t mb_crc16(const uint8_t *buf, size_t len);
/* RTU request: unit + PDU + CRC (low byte first). Returns the length. */
size_t mb_rtu_req_read(uint8_t *buf, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t count);
size_t mb_rtu_req_write_single(uint8_t *buf, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t value);
size_t mb_rtu_req_write_multi(uint8_t *buf, uint8_t unit, uint16_t addr, const uint16_t *regs, uint16_t count);
/* Parse RTU responses (CRC checked); same results as the TCP parsers. */
int mb_rtu_parse_read(const uint8_t *buf, size_t len, uint8_t unit, uint8_t fc,
                      uint16_t count, uint8_t *bits, uint16_t *regs);
int mb_rtu_parse_write(const uint8_t *buf, size_t len, uint8_t unit, uint8_t fc);

/* The client side is the backend hwd_backend_modbus (backend.h): it serves
 * both the "modbus" (TCP) and "modbus_rtu" sections. */

#endif
