#include "TSWIRE.H"

unsigned ts_le16(const unsigned char *p) {
    return (unsigned)p[0] | ((unsigned)p[1] << 8);
}
unsigned long ts_le32(const unsigned char *p) {
    return (unsigned long)p[0] | ((unsigned long)p[1] << 8) |
           ((unsigned long)p[2] << 16) | ((unsigned long)p[3] << 24);
}
unsigned long ts_elapsed(unsigned long start) {
    unsigned long now = ts_ticks();
    return now >= start ? now - start : 0x1800B0UL - start + now;
}
/* Tag high byte first, opcode last, including on an 8-bit PCMCIA bus. */
static void ring(unsigned off, unsigned command) {
    ts_wr8(off + 1, (unsigned char)(command >> 8));
    ts_wr8(off, (unsigned char)command);
}
static int complete(unsigned port, unsigned generation, unsigned tag,
                    unsigned len, unsigned char *out, unsigned *actual, int input) {
    unsigned n,i,result; unsigned long start,spins=0;
    start = ts_ticks();
    while (ts_rd(TS_SLOT + 2) != tag) {
        ts_poll();
        if (ts_elapsed(start) > 91UL || ++spins > 4000000UL)
            return TS_TIMEOUT; /* caller resets USB before releasing staging */
    }
    result = ts_rd(TS_SLOT + 4);
    if (result != TS_OK) return (int)result;
    if (ts_rd(TS_PORTS + port * 2) != (2u | (generation << 8))) return TS_GONE;
    n = ts_rd(TS_SLOT + 10);
    if (n > len) return TS_INVALID;
    if (input) for (i = 0; i < n; i++) out[i] = ts_rd8(TS_STAGE + i);
    *actual = n;
    return TS_OK;
}
int ts_control(unsigned port, unsigned generation, unsigned request_type,
               unsigned request, unsigned value, unsigned index,
               unsigned len, unsigned char *out, unsigned *actual) {
    unsigned tag;
    *actual = 0;
    /* Control requests remain read-only. MIDI commands use bulk OUT. */
    if (port >= 4 || !(request_type & 0x80) || !len || len > TS_MAX)
        return TS_INVALID;
    if (ts_rd(TS_SLOT) || ts_rd(TS_SLOT + 4) == 1) return TS_BUSY;
    if (ts_rd(TS_PORTS + port * 2) != (2u | (generation << 8)))
        return TS_GONE; /* AX88279A is full speed, never low speed. */
    tag = ((ts_rd(TS_SLOT + 2) & 255u) + 1u) & 255u;
    if (!tag) tag = 1;
    ts_wr(TS_SLOT + 6, 0); /* endpoint zero, flags zero */
    ts_wr(TS_SLOT + 8, len);
    ts_wr(TS_SLOT + 12, TS_STAGE);
    ts_wr(TS_SLOT + 14, generation);
    ts_wr8(TS_SLOT + 24, (unsigned char)port);
    ts_wr8(TS_SLOT + 16, (unsigned char)request_type);
    ts_wr8(TS_SLOT + 17, (unsigned char)request);
    ts_wr(TS_SLOT + 18, value);
    ts_wr(TS_SLOT + 20, index);
    ts_wr(TS_SLOT + 22, len);
    ring(TS_SLOT, 1u | (tag << 8));
    return complete(port,generation,tag,len,out,actual,1);
}

int ts_ax279a(const unsigned char *d, unsigned len) {
    return len == 18 && d[0] == 18 && d[1] == 1 &&
           ts_le16(d + 8) == 0x0B95u && ts_le16(d + 10) == 0x1790u &&
           ts_le16(d + 12) == 0x0500u;
}
/* 48-bit seconds without a compiler-specific 64-bit integer. */
int ts_clock(const unsigned char *raw, unsigned len, char *seconds,
             unsigned long *nanos) {
    unsigned char q[6];
    char reverse[16];
    unsigned i, n = 0, rem, v, nonzero;
    if (len != 12) return 0; /* ASIX AX_PTP_DATA_LEN, including two pad bytes */
    *nanos = ts_le32(raw);
    if (*nanos >= 1000000000UL) return 0;
    for (i = 0; i < 6; i++) q[i] = raw[i + 4];
    do {
        rem = nonzero = 0;
        for (i = 6; i > 0; i--) {
            v = rem * 256u + q[i - 1];
            q[i - 1] = (unsigned char)(v / 10u);
            rem = v % 10u;
            nonzero |= q[i - 1];
        }
        reverse[n++] = (char)('0' + rem);
    } while (nonzero);
    for (i = 0; i < n; i++) seconds[i] = reverse[n - i - 1];
    seconds[n] = 0;
    return 1;
}

int ts_bulk(unsigned port,unsigned generation,unsigned endpoint,
            unsigned len,unsigned char *data,unsigned *actual) {
    unsigned tag,i;
    *actual=0;
    if(port>=4 || !(endpoint&15) || (endpoint&0x70) || endpoint>255 ||
       !len || len>64) return TS_INVALID;
    if(ts_rd(TS_SLOT) || ts_rd(TS_SLOT+4)==1) return TS_BUSY;
    if(ts_rd(TS_PORTS+port*2)!=(2u|(generation<<8))) return TS_GONE;
    tag=((ts_rd(TS_SLOT+2)&255u)+1u)&255u; if(!tag)tag=1;
    if(!(endpoint&0x80)) for(i=0;i<len;i++)ts_wr8(TS_STAGE+i,data[i]);
    ts_wr(TS_SLOT+6,endpoint);ts_wr(TS_SLOT+8,len);
    ts_wr(TS_SLOT+12,TS_STAGE);ts_wr(TS_SLOT+14,generation);
    ts_wr8(TS_SLOT+24,(unsigned char)port);
    ring(TS_SLOT,1u|(tag<<8));
    return complete(port,generation,tag,len,data,actual,(endpoint&0x80)!=0);
}
