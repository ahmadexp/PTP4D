/* PicoPCMCIA v0.22 USB pass-through and AX88279A read-only protocol. */
#ifndef TSWIRE_H
#define TSWIRE_H
#define TS_STATE 0x04E2u
#define TS_GCTRL 0x04E4u
#define TS_GDONE 0x04E6u
#define TS_SLOT  0x04E8u
#define TS_PORTS 0x0568u
#define TS_STAGE 0x1000u
#define TS_MAX   256u
#define TS_OK    2
#define TS_TIMEOUT -1
#define TS_BUSY -2
#define TS_GONE -3
#define TS_SHORT -4
#define TS_INVALID -5
/* Supplied by DOS platform or the test harness. */
unsigned ts_rd(unsigned off);
void ts_wr(unsigned off, unsigned value);
unsigned char ts_rd8(unsigned off);
void ts_wr8(unsigned off, unsigned char value);
unsigned long ts_ticks(void);
void ts_poll(void);
int ts_control(unsigned port, unsigned generation, unsigned request_type,
               unsigned request, unsigned value, unsigned index,
               unsigned len, unsigned char *out, unsigned *actual);
int ts_bulk(unsigned port, unsigned generation, unsigned endpoint,
            unsigned len, unsigned char *data, unsigned *actual);
unsigned ts_le16(const unsigned char *p);
unsigned long ts_le32(const unsigned char *p);
int ts_ax279a(const unsigned char *device, unsigned len);
int ts_clock(const unsigned char *raw, unsigned len, char *seconds,
             unsigned long *nanos);
unsigned long ts_elapsed(unsigned long start);
#endif
