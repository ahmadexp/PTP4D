#ifndef PTP_CAPTURE_H
#define PTP_CAPTURE_H

/* Allocate sub-64-KiB banks before PICOCARD is held. No DOS I/O in capture. */
#ifdef PTP_FULL_CAPTURE
#include <stdlib.h>
#define PTP_RECORDS 2560u
static unsigned char *ptp_banks[5];
static void ptp_capture_free(void) {
    unsigned i;
    for(i=0;i<5;i++){free(ptp_banks[i]);ptp_banks[i]=0;}
}
static int ptp_capture_init(void) {
    unsigned i;
    for(i=0;i<5;i++) {
        ptp_banks[i]=(unsigned char *)malloc(512u*94u);
        if(!ptp_banks[i]){ptp_capture_free();return 0;}
    }
    return 1;
}
static unsigned char *ptp_record(unsigned index) {
    return ptp_banks[index/512u]+(index%512u)*94u;
}
#else
#define PTP_RECORDS 128u
static unsigned char ptp_records[PTP_RECORDS][94];
#define ptp_record(index) ptp_records[index]
#define ptp_capture_init() 1
#define ptp_capture_free() ((void)0)
#endif

#endif
