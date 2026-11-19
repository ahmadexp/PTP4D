#ifndef TSMIDI_H
#define TSMIDI_H
#define TM_FRAME 200u
#define TM_RAW 94u
typedef struct {
    unsigned used, len, version, kind;
    unsigned char frame[TM_FRAME], raw[TM_RAW];
} tm_parser;
unsigned tm_crc(const unsigned char *p, unsigned n);
int tm_event(tm_parser *p, const unsigned char event[4]);
int tm_endpoints(const unsigned char *d, unsigned len, unsigned *in_ep, unsigned *out_ep);
unsigned tm_command(unsigned long nonce, unsigned long seq, unsigned op,
                    unsigned profile, unsigned duration, const unsigned char mac[6],
                    unsigned char out[76]);
unsigned tm_ptp_command(unsigned long nonce, unsigned long seq, unsigned op,
                        unsigned profile, unsigned long generation,
                        unsigned char out[76], const unsigned char mac[6]);
double tm_signed(const unsigned char *p, unsigned bytes);
int tm_ptp_sample(const unsigned char raw[94], double *offset, double *delay, long *ppb);
#endif
