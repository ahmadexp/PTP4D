/* Exercise the actual DOS session code with a deterministic MIDI device and
   DOS date/time services. No live card, network, serial port or RTC access. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define main ptp4d_dos_main
#include "../src/PTP4D.C"
#undef main

static unsigned long ticks=100,elapsed_ticks,origin_ticks;
static pt_time system_origin;
static unsigned char queue[4096];
static unsigned queued,read_at,device_profile=1,armed,stops,starts,writes,commands;
static unsigned long device_gen=8,exchanges,last_exchange;
static tm_parser request;
static long device_ppb;
static int fault;
static const unsigned char device_mac[]={2,0,0,0,0,1};

void *mock_far(unsigned segment,unsigned offset) {
    assert(segment==0x40 && offset==0x6C);return &ticks;
}
static void put32(unsigned char *p,unsigned long v) {
    unsigned i;for(i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));
}
unsigned ts_le16(const unsigned char *p){return p[0]|(unsigned)p[1]<<8;}
unsigned long ts_le32(const unsigned char *p){return p[0]|(unsigned long)p[1]<<8|(unsigned long)p[2]<<16|(unsigned long)p[3]<<24;}
unsigned long ts_elapsed(unsigned long start){unsigned long now=ts_ticks();return now>=start?now-start:0x1800B0UL-start+now;}
int ts_ax279a(const unsigned char *p,unsigned n){(void)p;(void)n;return 0;}
int ts_clock(const unsigned char *p,unsigned n,char *s,unsigned long *ns){(void)n;(void)s;*ns=ts_le32(p);return *ns<1000000000UL;}
int bioskey(int command){(void)command;return 0;}
static pt_time now_system(void) {
    pt_time t=system_origin;unsigned long dt=elapsed_ticks-origin_ticks;
    t.seconds+=dt/18;t.nanoseconds+=(dt%18)*55555555UL;
    if(fault==10)t.nanoseconds+=dt*1000000UL;
    if(fault==12 && elapsed_ticks>500)t.seconds+=2;
    t.seconds+=t.nanoseconds/1000000000UL;t.nanoseconds%=1000000000UL;return t;
}
int int86(int interrupt,union REGS *in,union REGS *out) {
    unsigned ah=in->h.ah;pt_calendar c;pt_time t=now_system();
    if(interrupt==0x10)return 0;
    assert(interrupt==0x21);assert(pt_calendar_decode(&t,&c));
    if(ah==0x2A){out->x.cx=(unsigned short)c.year;out->h.dh=(unsigned char)c.month;out->h.dl=(unsigned char)c.day;}
    else if(ah==0x2C){out->h.ch=(unsigned char)c.hour;out->h.cl=(unsigned char)c.minute;out->h.dh=(unsigned char)c.second;out->h.dl=(unsigned char)c.centisecond;}
    else {
        if(ah==0x2B){c.year=in->x.cx;c.month=in->h.dh;c.day=in->h.dl;}
        else {assert(ah==0x2D);c.hour=in->h.ch;c.minute=in->h.cl;c.second=in->h.dh;c.centisecond=in->h.dl;}
        assert(pt_calendar_encode(&c,&system_origin));origin_ticks=elapsed_ticks;writes++;
        ticks=(c.hour*3600UL+c.minute*60UL+c.second)*18UL;out->h.al=0;
        if(fault==9)out->h.al=255;
    }
    return 0;
}
static void enqueue(const unsigned char *raw,unsigned n,unsigned version,unsigned kind) {
    unsigned char f[200];unsigned i,k,crc=tm_crc(raw,n),size=12+2*n,num;
    if(read_at==queued)read_at=queued=0;
    memcpy(f,"\360\175TSK",5);f[5]=(unsigned char)version;f[6]=(unsigned char)kind;
    for(i=0;i<n;i++){f[7+2*i]=raw[i]&127;f[8+2*i]=raw[i]>>7;}
    f[7+2*n]=crc&127;f[8+2*n]=(crc>>7)&1;f[9+2*n]=(crc>>8)&127;f[10+2*n]=crc>>15;f[11+2*n]=0xF7;
    for(i=0;i<size;i+=3) {
        num=size-i;if(num>3)num=3;
        assert(queued+4<=sizeof(queue));queue[queued++]=(unsigned char)(i+num<size?4:4+num);
        for(k=0;k<3;k++)queue[queued++]=k<num?f[i+k]:0;
    }
}
static void stamp(unsigned char *p) {
    /* Exact simulated source advances with the 18 Hz test tick clock. */
    memset(p,0,10);put32(p,1800000000UL+elapsed_ticks/18);
    put32(p+6,(elapsed_ticks%18)*55555555UL);
}
static void sample(void) {
    unsigned char raw[94];unsigned i;
    memset(raw,0,sizeof(raw));put32(raw,++exchanges);memcpy(raw+4,device_mac,6);
    raw[10]=device_profile==2?7:31;raw[11]=42;put32(raw+12,device_gen);stamp(raw+16);
    if(fault==3)put32(raw+12,device_gen+1);
    if(device_profile==2) {
        raw[74]=2;raw[75]=2;raw[83]=1;put32(raw+54,exchanges);put32(raw+62,exchanges);
        if(fault==4)put32(raw+70,1);
        enqueue(raw,94,3,0x22);return;
    }
    raw[26]=(unsigned char)exchanges;raw[27]=(unsigned char)(exchanges>>8);
    raw[28]=raw[26];raw[29]=raw[27];
    for(i=30;i<70;i+=10)stamp(raw+i);
    put32(raw+70,131072UL);put32(raw+78,131072000UL);
    put32(raw+86,(unsigned long)device_ppb);put32(raw+90,0x80000000UL);
    if(fault==6){raw[10]=3;}
    enqueue(raw,94,2,0x10);
}
static void reply(void) {
    unsigned char a[64];unsigned op=request.raw[8],len=32;
    long wanted;unsigned long token;
    memset(a,0,sizeof(a));memcpy(a,request.raw,9);
    assert(!memcmp(request.raw+16,device_mac,6));assert(request.raw[10]==42);
    if(op==2){armed=1;device_profile=request.raw[9];device_gen++;starts++;}
    if(op==3){armed=0;stops++;}
    a[10]=armed?2:9;a[11]=(unsigned char)device_profile;
    put32(a+16,device_gen);memcpy(a+22,device_mac,6);a[28]=42;a[29]=31;a[30]=(unsigned char)!armed;a[31]=(unsigned char)armed;
    if(op==5){a[20]=4;a[29]=63;assert(ts_le32(request.raw+12)==4);}
    if(op==6)a[29]=fault==1?31:95;
    if(op==4){assert(ts_le32(request.raw+12)==device_gen);commands++;}
    if(op==7) {
        assert(armed&&device_profile==3&&request.len==30&&ts_le32(request.raw+22)==device_gen);
        token=exchanges&65535UL;token|=token<<16;assert(ts_le32(request.raw+26)==token);
        wanted=(long)tm_signed(request.raw+12,4);assert(labs(wanted-device_ppb)<=10000L);
        assert(wanted>=-100000L&&wanted<=100000L);device_ppb=wanted;
        a[29]=95;len=44;put32(a+32,(unsigned long)wanted);
        put32(a+36,(unsigned long)(2147483648.0+(long)(2147483648.0*wanted/1e9)));
        if(fault==2)a[9]=4;
    }
    if(op==8) {
        len=64;a[29]=127;stamp(a+32);stamp(a+42);put32(a+56,0x80000000UL);put32(a+60,1);
        if(fault==7){a[46]=1;}
        if(fault==8)a[31]=0;
        if(fault==20){device_gen++;sample();device_gen--;}
    }
    if(op==3&&fault==5)return;
    if(op==7 && fault==16)a[22]^=1;
    if(op==7 && fault==17)a[4]^=1;
    if(op==2 && fault==19)return;
    /* A new measurement may arrive while waiting for a correction ACK. */
    if(fault==22 && op==7) {
        ticks+=5;elapsed_ticks+=5;last_exchange=elapsed_ticks;sample();
    }
    enqueue(a,len,3,0x21);
    if(op==7 && fault==15)queue[queued-5]^=1;
    if(op==8 && fault==18){ticks+=4;elapsed_ticks+=4;}
}
int ts_control(unsigned port,unsigned gen,unsigned type,unsigned req,unsigned val,unsigned idx,unsigned len,unsigned char *out,unsigned *actual) {
    static const unsigned char cfg[]={9,2,32,0,1,1,0,0x80,50,9,4,1,0,2,1,3,0,0,7,5,0x84,2,64,0,0,7,5,5,2,64,0,0};
    (void)port;(void)gen;(void)req;(void)val;(void)idx;
    if(type==0xC0){memcpy(out,device_mac,6);*actual=6;return TS_OK;}
    memcpy(out,cfg,len);*actual=len;return TS_OK;
}
int ts_bulk(unsigned port,unsigned gen,unsigned ep,unsigned len,unsigned char *data,unsigned *actual) {
    unsigned i,n;(void)port;(void)gen;
    if(ep==5) {
        for(i=0;i<len;i+=4)if(tm_event(&request,data+i))reply();*actual=len;return TS_OK;
    }
    assert(ep==0x84);
    if(read_at==queued) {
        /* Real USB IN waits for data. An unnecessary read after a complete
           measurement can block until the next exchange invalidates its token. */
        if((fault==21||fault==22) && armed) {
            ticks+=5;elapsed_ticks+=5;last_exchange=elapsed_ticks;sample();
        } else {
        ticks=(ticks+1)%0x1800B0UL;elapsed_ticks++;
        if(armed && fault!=13 && !(fault==14&&elapsed_ticks>200) && elapsed_ticks-last_exchange>=5){last_exchange=elapsed_ticks;sample();}
        }
    }
    n=queued-read_at;if(n>len)n=len;memcpy(data,queue+read_at,n);read_at+=n;*actual=n;return TS_OK;
}
int main(int argc,char **argv) {
    int r;assert(argc==4);fault=atoi(argv[1]);options.servo=atoi(argv[2]);options.role=atoi(argv[3]);
    options.sync=(fault>=6 || fault==0)?SYNC_PHC_DOS:SYNC_NONE;
    if(fault>=21)options.sync=SYNC_NONE;
    if(options.role==2)options.sync=SYNC_NONE;
    options.valid_seconds=fault==11?10:120;options.track=1;ptp_mode=1;ptp_seconds=75;
    selected=0;selected_gen=1;system_origin.seconds=1790000000UL;system_origin.nanoseconds=0;
    r=ptp_run();
    if(fault==0 || fault==10 || fault==11 || fault==21 || fault==22) {
        assert(r==TS_OK&&starts==1&&stops==1&&ptp_stopped&&commands>(fault==11?1u:10u));
        if(options.role==1){
            if(fault>=21)assert(bridge_updates==0&&writes==0);
            else assert(bridge_updates>=1&&writes>=2);
            if(options.servo)assert(host_commands>(fault==11?20UL:100UL));
        }
        else assert(gm_syncs>100&&writes==0);
        if(fault==10)assert(bridge_updates>=3);
        if(fault==11)assert(elapsed_ticks<230);
    }else if(fault==1){assert(r!=TS_OK&&starts==0&&stops==0&&writes==0);}
    else {assert(r!=TS_OK&&stops==1);if(fault==12||fault==14)assert(writes==2);else if(fault!=9)assert(writes==0);}
    if(fault==5)assert(!ptp_stopped);else if(stops)assert(ptp_stopped);
    printf("PASS session fault=%d servo=%d role=%d, result=%d, writes=%u, host ACKs=%lu\n",fault,options.servo,options.role,r,writes,host_commands);
    return 0;
}
