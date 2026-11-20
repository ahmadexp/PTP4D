#include "CLOCK.H"
#include "TSWIRE.H"
#define DAY_TICKS 0x1800B0UL
static int leap(unsigned y){return !(y%4) && (y%100 || !(y%400));}
static unsigned days(unsigned y,unsigned m) {
    static const unsigned char d[]={31,28,31,30,31,30,31,31,30,31,30,31};
    return d[m-1]+(m==2 && leap(y));
}
int pt_calendar_encode(const pt_calendar *c,pt_time *t) {
    unsigned y,m;unsigned long d=0;
    if(c->year<1980||c->year>2099||c->month<1||c->month>12||c->day<1||
       c->day>days(c->year,c->month)||c->hour>23||c->minute>59||c->second>59||c->centisecond>99)return 0;
    for(y=1970;y<c->year;y++)d+=365+leap(y);
    for(m=1;m<c->month;m++)d+=days(c->year,m);
    t->seconds=(d+c->day-1)*86400UL+c->hour*3600UL+c->minute*60UL+c->second;
    t->nanoseconds=c->centisecond*10000000UL;return 1;
}
int pt_calendar_decode(const pt_time *t,pt_calendar *c) {
    unsigned long d,s;unsigned y=1970,m=1,n;
    if(t->seconds<315532800UL||t->seconds>4102444799UL||t->nanoseconds>=1000000000UL)return 0;
    d=t->seconds/86400UL;s=t->seconds%86400UL;
    while(d>=(n=365+leap(y))){d-=n;y++;}
    while(d>=(n=days(y,m))){d-=n;m++;}
    c->year=y;c->month=m;c->day=(unsigned)d+1;c->hour=(unsigned)(s/3600UL);
    c->minute=(unsigned)(s%3600UL/60UL);c->second=(unsigned)(s%60UL);
    c->centisecond=(unsigned)(t->nanoseconds/10000000UL);return 1;
}
int pt_time_advance(pt_time *t,unsigned long ns) {
    unsigned long sec=ns/1000000000UL;
    ns=ns%1000000000UL+t->nanoseconds;
    if(ns>=1000000000UL){sec++;ns-=1000000000UL;}
    if(t->seconds>0xFFFFFFFFUL-sec)return 0;
    t->seconds+=sec;t->nanoseconds=ns;return 1;
}
int pt_clock_target(const unsigned char a[64],unsigned long ticks,const pt_options *o,pt_time *t) {
    unsigned long rx,tx,rns,tns,span,rtt;long shift;pt_calendar check;
    /* PHC's 48-bit seconds must fit the supported civil epoch; never truncate. */
    if(a[36]||a[37]||a[46]||a[47]||ts_le32(a+60)!=1UL||ticks>2)return 0;
    rx=ts_le32(a+32);tx=ts_le32(a+42);rns=ts_le32(a+38);tns=ts_le32(a+48);
    if(rns>=1000000000UL||tns>=1000000000UL||tx<rx||tx-rx>1)return 0;
    if(tx==rx && tns<rns)return 0;
    span=(tx-rx)*1000000000UL+tns-rns;
    if(span>110000000UL)return 0;
    rtt=ticks*54925493UL;
    /* Tick quantization allows one tick of uncertainty in measured RTT. */
    if(span>rtt+54925493UL)return 0;
    t->seconds=tx;t->nanoseconds=tns;
    if(!pt_time_advance(t,rtt>span?(rtt-span)/2:0))return 0;
    shift=(long)o->zone_minutes*60L-(o->scale?o->tai_offset:0);
    if(shift<0){if(t->seconds<(unsigned long)-shift)return 0;t->seconds-=(unsigned long)-shift;}
    else{if(t->seconds>0xFFFFFFFFUL-(unsigned long)shift)return 0;t->seconds+=(unsigned long)shift;}
    return pt_calendar_decode(t,&check);
}
long pt_clock_difference(const pt_time *t,const pt_time *c,int *large) {
    long sec;*large=0;
    if(t->seconds>=c->seconds) {
        if(t->seconds-c->seconds>86400UL){*large=1;return 0;}
        sec=(long)(t->seconds-c->seconds);
    }else {
        if(c->seconds-t->seconds>86400UL){*large=1;return 0;}
        sec=-(long)(c->seconds-t->seconds);
    }
    return sec*100L+(long)(t->nanoseconds/10000000UL)-(long)(c->nanoseconds/10000000UL);
}
unsigned long pt_timer_read(pt_timer *t,unsigned long raw) {
    if(!t->ready){t->ready=1;t->last=raw;}
    t->total+=(raw>=t->last?raw-t->last:DAY_TICKS-t->last+raw);
    t->total%=DAY_TICKS;t->last=raw;return t->total;
}
void pt_timer_rebase(pt_timer *t,unsigned long raw){t->last=raw;t->ready=1;}
