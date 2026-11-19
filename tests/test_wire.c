#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "TSWIRE.H"
static unsigned char mem[0x4000];
static unsigned long ticks;
static int scenario, polls, writes, low_written;
unsigned ts_rd(unsigned o) { return mem[o] | ((unsigned)mem[o+1] << 8); }
void ts_wr(unsigned o, unsigned v) { mem[o] = v; mem[o+1] = v >> 8; writes++; }
unsigned char ts_rd8(unsigned o) { return mem[o]; }
void ts_wr8(unsigned o, unsigned char v) {
    mem[o] = v; writes++;
    if (o == TS_SLOT) {
        assert(mem[o+1] != 0); /* opcode cannot arrive ahead of tag */
        low_written++;
    }
}
unsigned long ts_ticks(void) { return ticks; }
void ts_poll(void) {
    ticks++; polls++;
    if (scenario == 1 || polls != 2) return;
    ts_wr(TS_SLOT, 0);
    ts_wr(TS_SLOT+4, scenario == 2 ? 3 : 2);
    ts_wr(TS_SLOT+10, scenario == 3 ? 65 : 12);
    if (scenario == 4) ts_wr(TS_PORTS, 2u | (8u << 8));
    ts_wr(TS_SLOT+2, 1); /* previous completion was 255: wraps to 1 */
}
static void init(void) {
    memset(mem, 0, sizeof mem); ticks = 0; polls = writes = low_written = 0;
    ts_wr(TS_PORTS, 2u | (7u << 8)); ts_wr(TS_SLOT+2, 255);
    memset(mem+TS_STAGE, 0x5A, 64);
}
int main(void) {
    unsigned char raw[12] = {0}, out[TS_MAX], desc[18] = {18,1};
    char sec[16]; unsigned long ns; unsigned n; int r, before;
    assert(ts_clock(raw,12,sec,&ns) && !strcmp(sec,"0") && ns==0);
    memset(raw+4,255,6); raw[0]=0xFF;raw[1]=0xC9;raw[2]=0x9A;raw[3]=0x3B;
    assert(ts_clock(raw,12,sec,&ns));
    assert(!strcmp(sec,"281474976710655") && ns==999999999UL);
    raw[0]=0;raw[1]=0xCA;
    assert(!ts_clock(raw,12,sec,&ns)); assert(!ts_clock(raw,10,sec,&ns));
    memset(raw,0,12); raw[8]=1;
    assert(ts_clock(raw,12,sec,&ns) && !strcmp(sec,"4294967296"));
    desc[8]=0x95;desc[9]=0x0B;desc[10]=0x90;desc[11]=0x17;desc[13]=5;
    assert(ts_ax279a(desc,18)); desc[13]=4; assert(!ts_ax279a(desc,18));
    for(scenario=0;scenario<5;scenario++) {
        init();
        r=ts_control(0,7,0xC0,0x11,0x1010,0x12,12,out,&n);
        assert(low_written==1);
        assert(mem[TS_SLOT+16]==0xC0 && mem[TS_SLOT+17]==0x11);
        assert(ts_rd(TS_SLOT+18)==0x1010 && ts_rd(TS_SLOT+20)==0x12);
        assert(ts_rd(TS_SLOT+22)==12 && ts_rd(TS_SLOT+12)==0x1000);
        if(scenario==0) assert(r==TS_OK && n==12 && out[11]==0x5A);
        if(scenario==1) assert(r==TS_TIMEOUT && n==0);
        if(scenario==2) assert(r==3 && n==0);
        if(scenario==3) assert(r==TS_INVALID && n==0);
        if(scenario==4) assert(r==TS_GONE && n==0);
    }
    init(); before=writes;
    assert(ts_control(0,7,0x40,0x11,0x1010,0x12,12,out,&n)==TS_INVALID);
    assert(writes==before); /* rejected OUT request has no side effects */
    ts_wr(TS_SLOT+4,1); before=writes;
    assert(ts_control(0,7,0xC0,0x11,0x1010,0x12,12,out,&n)==TS_BUSY);
    assert(writes==before);
    init(); ticks=0; scenario=0; ts_wr(TS_SLOT+2,0);
    assert(ts_control(4,7,0xC0,0x11,0x1010,0x12,12,out,&n)==TS_INVALID);
    assert(ts_control(0,7,0xC0,0x11,0x1010,0x12,TS_MAX+1,out,&n)==TS_INVALID);
    assert(ts_control(0,8,0xC0,0x11,0x1010,0x12,12,out,&n)==TS_GONE);
    init(); scenario=0;
    assert(ts_bulk(0,7,0x84,64,out,&n)==TS_OK && n==12 && out[0]==0x5A);
    assert(ts_rd(TS_SLOT+6)==0x84);
    init(); scenario=0; memset(out,0xA7,12);
    assert(ts_bulk(0,7,5,12,out,&n)==TS_OK && n==12);
    assert(mem[TS_STAGE]==0xA7 && ts_rd(TS_SLOT+6)==5);
    init(); before=writes;
    assert(ts_bulk(0,7,0,12,out,&n)==TS_INVALID && writes==before);
    assert(ts_bulk(0,7,0x84,65,out,&n)==TS_INVALID && writes==before);
    ticks=4; assert(ts_elapsed(0x1800B0UL-5)==9);
    puts("PASS: 48-bit clock decoding, limits, identity, setup bytes, tag wrap,");
    puts("      busy slot, stale generation, timeout, stall, oversized reply, OUT rejection.");
    return 0;
}
