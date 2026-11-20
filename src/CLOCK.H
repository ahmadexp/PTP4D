#ifndef PT_CLOCK_H
#define PT_CLOCK_H
#include "OPTIONS.H"
typedef struct {unsigned year,month,day,hour,minute,second,centisecond;} pt_calendar;
typedef struct {unsigned long seconds,nanoseconds;} pt_time;
int pt_calendar_encode(const pt_calendar *c,pt_time *t);
int pt_calendar_decode(const pt_time *t,pt_calendar *c);
int pt_clock_target(const unsigned char ack[64],unsigned long roundtrip_ticks,
                    const pt_options *o,pt_time *target);
/* Signed target-current centiseconds, or 0 with *large set for >1 day. */
long pt_clock_difference(const pt_time *target,const pt_time *current,int *large);
int pt_time_advance(pt_time *t,unsigned long ns);
/* BIOS tick counter extension; rebase after an intentional DOS clock write. */
typedef struct {unsigned long last,total;int ready;} pt_timer;
unsigned long pt_timer_read(pt_timer *t,unsigned long raw);
void pt_timer_rebase(pt_timer *t,unsigned long raw);
#endif
