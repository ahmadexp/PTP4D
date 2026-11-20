#ifdef __BORLANDC__
#include "TESTDOS.H"
#else
#include <assert.h>
#endif
#include <stdio.h>
#include <string.h>
#include "TSWIRE.H"
#include "TSMIDI.H"
/* Unused hardware platform for linking the shared decoder. */
unsigned ts_rd(unsigned o){(void)o;return 0;}
void ts_wr(unsigned o,unsigned v){(void)o;(void)v;}
unsigned char ts_rd8(unsigned o){(void)o;return 0;}
void ts_wr8(unsigned o,unsigned char v){(void)o;(void)v;}
unsigned long ts_ticks(void){return 0;}
void ts_poll(void){}
static unsigned packets(const unsigned char *raw,unsigned n,unsigned version,unsigned kind,unsigned char *out){
    unsigned char f[200]; unsigned i,k,bytes=0,crc=tm_crc(raw,n),size=12+2*n;
    memcpy(f,"\360\175TSK",5);f[5]=version;f[6]=kind;
    for(i=0;i<n;i++){f[7+i*2]=raw[i]&127;f[8+i*2]=raw[i]>>7;}
    f[7+2*n]=crc&127;f[8+2*n]=(crc>>7)&1;
    f[9+2*n]=(crc>>8)&127;f[10+2*n]=crc>>15;f[11+2*n]=0xF7;
    for(i=0;i<size;i+=3){unsigned num=size-i;if(num>3)num=3;
        out[bytes++]=i+num<size?4:4+num;
        for(k=0;k<3;k++)out[bytes++]=k<num?f[i+k]:0;
    }return bytes;
}
static void put32(unsigned char *p,unsigned long v){unsigned i;for(i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static void extended_tests(void) {
    unsigned char wire[96],mac[6]={2,0,0,0,0,1},a[64];
    tm_parser p;unsigned i,n;long ppb;
    n=tm_host_command(42,10,-99999L,21,0xFFFF0000UL,wire,mac);assert(n==96);
    memset(&p,0,sizeof(p));for(i=0;i<n;i+=4)tm_event(&p,wire+i);
    assert(p.len==30&&p.raw[8]==7&&p.raw[9]==3&&p.raw[11]==0);
    assert(ts_le32(p.raw+12)==0xFFFE7961UL&&ts_le32(p.raw+22)==21&&ts_le32(p.raw+26)==0xFFFF0000UL);
    assert(!tm_host_command(42,10,100001L,21,0,wire,mac));
    assert(!tm_host_command(42,10,0,0,0,wire,mac));
    assert(!tm_host_command(0,10,0,21,0,wire,mac));
    assert(tm_ptp_command(42,10,6,3,0,wire,mac)==76);
    assert(tm_ptp_command(42,10,8,3,0,wire,mac)==76);
    assert(!tm_ptp_command(42,10,9,3,0,wire,mac));
    assert(!tm_ptp_command(42,10,10,2,0,wire,mac));
    memset(&p,0,sizeof(p));p.len=44;p.version=3;p.kind=0x21;
    put32(p.raw,42);put32(p.raw+4,10);p.raw[8]=7;memcpy(p.raw+22,mac,6);p.raw[28]=42;
    assert(tm_ack_matches(&p,42,10,7,mac));
    assert(!tm_ack_matches(&p,42,11,7,mac));assert(!tm_ack_matches(&p,43,10,7,mac));
    p.raw[22]^=1;assert(!tm_ack_matches(&p,42,10,7,mac));p.raw[22]^=1;
    p.len=32;assert(!tm_ack_matches(&p,42,10,7,mac));p.len=44;
    p.raw[28]=0;assert(!tm_ack_matches(&p,42,10,7,mac));
    memset(a,0,sizeof(a));a[10]=2;a[11]=3;put32(a+16,21);a[29]=95;a[31]=1;
    for(ppb=-100000L;ppb<=100000L;ppb++) {
        long change=(long)(2147483648.0*ppb/1000000000.0);
        put32(a+32,(unsigned long)ppb);put32(a+36,(unsigned long)(2147483648.0+change));
        assert(tm_host_ack(a,21,ppb));
    }
    assert(!tm_host_ack(a,22,100000L));a[36]^=1;assert(!tm_host_ack(a,21,100000L));a[36]^=1;
    a[29]=31;assert(!tm_host_ack(a,21,100000L));a[29]=95;
    put32(a+40,2000000001UL);assert(!tm_host_ack(a,21,100000L));
    puts("PASS: profile 3, host commands, exact full-range addends and correlated extended ACKs.");
}
int main(void){
    tm_parser p;unsigned char raw[94],wire[268],mac[6]={0x02,0,0,0,0,0x02};
    unsigned char cfg[]={9,2,32,0,1,1,0,0x80,50,9,4,1,0,2,1,3,0,0,7,5,0x84,2,64,0,0,7,5,5,2,64,0,0};
    unsigned in,out,n,i,got; double offset,delay;long ppb;
    extended_tests();
    assert(tm_crc((const unsigned char *)"123456789L",9)==0x29B1);
    assert(tm_endpoints(cfg,sizeof cfg,&in,&out) && in==0x84 && out==5);
    cfg[23]=1;assert(!tm_endpoints(cfg,sizeof cfg,&in,&out));cfg[23]=0;
    cfg[29]=32;assert(!tm_endpoints(cfg,sizeof cfg,&in,&out));cfg[29]=64;
    cfg[9]=255;assert(!tm_endpoints(cfg,sizeof cfg,&in,&out));cfg[9]=9;
    for(i=0;i<94;i++)raw[i]=(unsigned char)(i*17);
    n=packets(raw,94,2,0x10,wire);assert(n==268);
    memset(&p,0,sizeof p);got=0;
    for(i=0;i<n;i+=4)got+=tm_event(&p,wire+i);
    assert(got==1 && p.len==94 && p.version==2 && p.kind==0x10 && !memcmp(raw,p.raw,94));
    wire[13]^=1;memset(&p,0,sizeof p);got=0;
    for(i=0;i<n;i+=4)got+=tm_event(&p,wire+i);
    assert(!got);wire[13]^=1;
    wire[11]=2;memset(&p,0,sizeof p);got=0; /* noncanonical high bit */
    for(i=0;i<n;i+=4)got+=tm_event(&p,wire+i);
    assert(!got);
    n=packets(raw,64,3,0x21,wire);assert(n==188);
    memset(&p,0,sizeof p);got=0;
    for(i=0;i<n;i+=4)got+=tm_event(&p,wire+i);
    assert(got==1 && p.len==64 && !memcmp(raw,p.raw,64));
    /* Missing beginning, other cable and truncated termination are rejected. */
    memset(&p,0,sizeof p);got=0;
    for(i=4;i<n;i+=4)got+=tm_event(&p,wire+i);assert(!got);
    for(i=0;i<n;i+=4)wire[i]|=0x10;
    memset(&p,0,sizeof p);got=0;for(i=0;i<n;i+=4)got+=tm_event(&p,wire+i);assert(!got);
    n=tm_command(0x12345678UL,7,2,4,5,mac,wire);assert(n==76);
    memset(&p,0,sizeof p);got=0;for(i=0;i<n;i+=4)got+=tm_event(&p,wire+i);
    assert(got==1 && p.len==22 && p.kind==0x20 && p.version==3);
    assert(ts_le32(p.raw)==0x12345678UL && ts_le32(p.raw+4)==7);
    assert(p.raw[8]==2 && p.raw[9]==4 && p.raw[10]==42 && !p.raw[11]);
    assert(ts_le32(p.raw+12)==5 && !memcmp(p.raw+16,mac,6));
    assert(!tm_command(1,1,2,1,5,mac,wire));
    assert(!tm_command(1,1,2,4,60,mac,wire));
    for(i=4;i<=10;i++)if(i!=8)assert(!tm_command(1,1,i,4,0,mac,wire));
    assert(tm_command(1,1,8,4,0,mac,wire)==76);
    assert(tm_command(1,1,3,4,0,mac,wire)==76);
    n=tm_ptp_command(1,2,2,1,0,wire,mac);assert(n==76);
    memset(&p,0,sizeof p);got=0;for(i=0;i<n;i+=4)got+=tm_event(&p,wire+i);
    assert(got==1 && p.raw[8]==2 && p.raw[9]==1 && p.raw[11]==1 && ts_le32(p.raw+12)==15);
    n=tm_ptp_command(1,3,4,1,1234,wire,mac);assert(n==76);
    memset(&p,0,sizeof p);got=0;for(i=0;i<n;i+=4)got+=tm_event(&p,wire+i);
    assert(got==1 && p.raw[8]==4 && ts_le32(p.raw+12)==1234);
    assert(!tm_ptp_command(1,3,4,1,0,wire,mac));
    assert(!tm_ptp_command(1,3,2,1,1234,wire,mac));
    assert(!tm_ptp_command(1,3,9,1,0,wire,mac));
    memset(raw,255,8);assert(tm_signed(raw,8)==-1.0);
    raw[0]=0;assert(tm_signed(raw,8)==-256.0);
    memset(raw,0,94);raw[10]=31;raw[11]=42;raw[12]=1;
    memset(raw+70,255,8);raw[70]=raw[71]=0;raw[72]=0xFE;
    raw[78]=0;raw[79]=0;raw[80]=5; /* delay Q17=327680L -> 2.5ns */
    memset(raw+86,255,4);raw[86]=246;raw[90]=1;
    assert(tm_ptp_sample(raw,&offset,&delay,&ppb));
    assert(offset==-1 && delay==2.5 && ppb==-10);
    raw[39]=0x40;assert(!tm_ptp_sample(raw,&offset,&delay,&ppb));raw[39]=0;
    raw[10]=3;assert(!tm_ptp_sample(raw,&offset,&delay,&ppb));raw[10]=31;
    raw[85]=128;assert(!tm_ptp_sample(raw,&offset,&delay,&ppb));
    puts("PASS: PTP lease encoding, generation checks, signed Q17 and sample bounds.");
    puts("PASS: MIDI descriptor bounds, CRC, framing, fragmentation, corruption,");
    puts("      canonical encoding, 64-byte ACK, identity and bounded command whitelist.");
    return 0;
}
