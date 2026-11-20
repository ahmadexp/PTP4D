#ifdef __BORLANDC__
#include "TESTDOS.H"
#else
#include <assert.h>
#endif
#include <stdio.h>
#include <string.h>
#include "CLOCK.H"
unsigned long ts_le32(const unsigned char *p){return (unsigned long)p[0]|((unsigned long)p[1]<<8)|((unsigned long)p[2]<<16)|((unsigned long)p[3]<<24);}
static void put(unsigned char *p,unsigned long v){unsigned i;for(i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
int main(void) {
    pt_calendar c,d;pt_time t,u;pt_options o;pt_timer timer;
    unsigned char ack[64];unsigned y,m,day;int large;
    memset(&c,0,sizeof(c));memset(&o,0,sizeof(o));memset(&timer,0,sizeof(timer));
    /* Exhaust every valid day, including 2000, and reject invalid month ends. */
    for(y=1980;y<=2099;y++)for(m=1;m<=12;m++)for(day=1;day<=31;day++) {
        c.year=y;c.month=m;c.day=day;c.hour=23;c.minute=59;c.second=59;c.centisecond=99;
        if(pt_calendar_encode(&c,&t)){assert(pt_calendar_decode(&t,&d));assert(!memcmp(&c,&d,sizeof(c)));}
    }
    c.year=2000;c.month=2;c.day=29;assert(pt_calendar_encode(&c,&t));
    assert(pt_time_advance(&t,10000000UL)&&pt_calendar_decode(&t,&d));assert(d.month==3&&d.day==1&&d.hour==0);
    c.year=2100;assert(!pt_calendar_encode(&c,&t));c.year=2001;assert(!pt_calendar_encode(&c,&t));
    memset(ack,0,sizeof(ack));put(ack+32,1800000037UL);put(ack+42,1800000037UL);
    put(ack+38,999000000UL);put(ack+48,999500000UL);put(ack+60,1);
    o.scale=1;o.tai_offset=37;o.zone_minutes=-480;
    assert(pt_clock_target(ack,1,&o,&t));assert(t.seconds==1800000001UL-28800UL);
    assert(t.nanoseconds<30000000UL);
    ack[46]=1;assert(!pt_clock_target(ack,1,&o,&t));ack[46]=0;
    put(ack+60,3);assert(!pt_clock_target(ack,1,&o,&t));put(ack+60,1);
    assert(!pt_clock_target(ack,3,&o,&t));
    put(ack+42,0);assert(!pt_clock_target(ack,1,&o,&t));
    put(ack+32,1);put(ack+42,1);assert(!pt_clock_target(ack,1,&o,&t));
    t.seconds=0xFFFFFFFFUL;t.nanoseconds=999999999UL;assert(!pt_time_advance(&t,1));
    t.seconds=1800000000UL;t.nanoseconds=10000000UL;u=t;u.seconds--;u.nanoseconds=990000000UL;
    assert(pt_clock_difference(&t,&u,&large)==2&&!large);
    assert(pt_clock_difference(&u,&t,&large)==-2&&!large);
    u.seconds=1;assert(pt_clock_difference(&t,&u,&large)==0&&large);
    assert(pt_timer_read(&timer,0x1800AFUL)==0);
    assert(pt_timer_read(&timer,2)==3);
    pt_timer_rebase(&timer,1000000UL);assert(pt_timer_read(&timer,1000002UL)==5);
    pt_timer_rebase(&timer,100);assert(pt_timer_read(&timer,101)==6);
    puts("PASS: 1980..2099 Gregorian days, UTC/TAI/zone, rollover, capture bounds and deadline rebasing.");return 0;
}
