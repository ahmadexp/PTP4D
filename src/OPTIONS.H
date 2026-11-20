#ifndef OPTIONS_H
#define OPTIONS_H
#define OPT_PASSIVE 0
#define OPT_PTP 1
#define OPT_CLOCK 2
#define OPT_LIST 3
#define OPT_HOST 4
#define OPT_CARD 5
#define SYNC_NONE 0
#define SYNC_PHC_DOS 1
#define SYNC_DOS_PHC 2
typedef struct {
    int action, role, servo, sync, port, diag, track;
    int scale, tai_offset, dos_local, zone_minutes;
    unsigned seconds, valid_seconds;
} pt_options;
/* 1 success, 2 help, 0 error. No hardware access. */
int pt_options_parse(int argc, char **argv, pt_options *o, const char **error);
const char *pt_servo_name(int servo);
void pt_help(void);
#endif
