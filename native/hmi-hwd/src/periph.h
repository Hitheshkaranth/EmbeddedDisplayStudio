/*
 * periph.h -- the pure (hardware-free) parts of the peripheral backends,
 * unit-tested in tests/test_periph.c and tests/test_can.c.
 *
 * FROZEN.
 */
#ifndef HWD_PERIPH_H
#define HWD_PERIPH_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* ---- CAN (A2, can.c) -------------------------------------------------- */
/* DBC bit numbering: little (Intel) counts start_bit from the LSB of byte 0;
 * big (Motorola) start_bit is the MSB's position in the sawtooth numbering
 * (bit 7 of byte 0 is 7, bit 0 of byte 0 is 0, bit 7 of byte 1 is 15, ...). */
uint64_t can_get_bits(const uint8_t data[8], int start_bit, int length, bool big_endian);
void can_set_bits(uint8_t data[8], int start_bit, int length, bool big_endian, uint64_t raw);
/* Sign-extend a length-bit raw value. */
int64_t can_sign_extend(uint64_t raw, int length);
/* "0x123" / "291" -> id; false on bad text or out of range (11/29 bit). */
bool can_parse_id(const char *text, bool extended, uint32_t *id);
/* "0102AABB" or "01 02 aa bb" -> bytes (<= 8); returns the count or -1. */
int can_parse_hex(const char *text, uint8_t out[8]);

/* ---- HID (A4, hid.c) -------------------------------------------------- */
/* US layout: the character an evdev key code types (shift applied), or 0
 * for keys that type nothing (shift, ctrl, enter ...). KEY_ENTER/KEY_TAB
 * are recognised by the caller as eol. */
char hid_key_char(int code, bool shift);

/* ---- sensors (A4, sensors.c) ------------------------------------------ */
typedef enum { SENS_U8, SENS_I8, SENS_U16, SENS_I16, SENS_U32, SENS_I32, SENS_F32 } sens_type;
bool sens_parse_type(const char *name, sens_type *t);
int sens_type_bytes(sens_type t);
/* Generic decode: bytes -> raw (byte_order), & mask (0 = none), >> shift,
 * then raw * scale + offset. */
double sens_decode(const uint8_t *buf, sens_type t, bool big_endian, uint32_t mask, int shift,
                   double scale, double offset);
/* Presets, from the device's own register bytes. */
double sens_tmp102_c(const uint8_t b[2]);        /* also lm75 (12-bit left aligned) */
double sens_sht3x_temp_c(const uint8_t b[6]);    /* b = T msb, lsb, crc, RH msb, lsb, crc */
double sens_sht3x_rh(const uint8_t b[6]);
bool sens_sht3x_crc_ok(const uint8_t b[6]);      /* CRC-8 poly 0x31 init 0xFF */
double sens_ads1115_volts(const uint8_t b[2]);   /* conversion register, +-4.096 V */
double sens_ina219_bus_v(const uint8_t b[2]);    /* bus voltage register */
double sens_ina219_current_a(const uint8_t b[2], double shunt_ohm);  /* shunt voltage register */

#endif
