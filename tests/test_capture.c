/* Verify all capture banks with the native and 16-bit DOS compilers. */
#ifdef __BORLANDC__
#include "TESTDOS.H"
#else
#include <assert.h>
#endif
#include <stdio.h>
#include <string.h>
#include "CAPTURE.H"

int main(void) {
    unsigned i,j;unsigned char value[94];
    assert(ptp_capture_init());
    for(i=0;i<PTP_RECORDS;i++) {
        for(j=0;j<94;j++)value[j]=(unsigned char)((i+j)^(i>>8));
        memcpy(ptp_record(i),value,94);
    }
    for(i=0;i<PTP_RECORDS;i++)
        for(j=0;j<94;j++)assert(ptp_record(i)[j]==(unsigned char)((i+j)^(i>>8)));
    printf("PASS capture: %u independent 94-byte records\n",PTP_RECORDS);
    ptp_capture_free();
    return 0;
}
