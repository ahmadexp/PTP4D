/* TimeStick MIDI wire format, implemented from ts_midi_telemetry/control.c. */
#include <string.h>
#include "TSWIRE.H"
#include "TSMIDI.H"
unsigned tm_crc(const unsigned char *p, unsigned n) {
    unsigned c=0xFFFFu, i;
    while(n--) {
        c ^= (unsigned)*p++ << 8;
        for(i=0;i<8;i++) c=((c<<1)^((c&0x8000u)?0x1021u:0))&0xFFFFu;
    }
    return c;
}
static int decode(tm_parser *p) {
    unsigned i, n, crc;
    unsigned char decoded[TM_RAW+2];
    if(p->used<12 || memcmp(p->frame,"\360\175TSK",5) ||
       p->frame[p->used-1]!=0xF7 || ((p->used-8)&1)) return 0;
    n=(p->used-8)/2;
    if(n<2 || n>TM_RAW+2) return 0;
    for(i=0;i<n;i++) {
        if(p->frame[7+i*2]>127 || p->frame[8+i*2]>1) return 0;
        decoded[i]=p->frame[7+i*2]|(p->frame[8+i*2]<<7);
    }
    crc=ts_le16(decoded+n-2);
    if(tm_crc(decoded,n-2)!=crc) return 0;
    p->version=p->frame[5]; p->kind=p->frame[6]; p->len=n-2;
    memcpy(p->raw,decoded,n-2); return 1;
}
int tm_event(tm_parser *p, const unsigned char e[4]) {
    unsigned cin=e[0]&15, n, i; int result=0;
    if(e[0]&0xF0) return 0; /* only cable zero */
    if(cin==15 && e[1]>=0xF8) return 0; /* realtime does not break SysEx */
    if(cin<4 || cin>7) { p->used=0; return 0; }
    n=cin==4?3:cin-4;
    for(i=1;i<=n;i++) {
        if(e[i]==0xF0) p->used=0;
        else if(!p->used) return 0;
        if(p->used>=TM_FRAME) { p->used=0; return 0; }
        p->frame[p->used++]=e[i];
        if(e[i]==0xF7) {
            if(cin!=4 && i==n) result=decode(p);
            p->used=0; return result;
        }
        if(e[i]>=0x80 && e[i]!=0xF0) { p->used=0; return 0; }
    }
    if(cin!=4) p->used=0; /* terminating CIN must include F7 */
    return 0;
}
int tm_endpoints(const unsigned char *d,unsigned len,unsigned *in_ep,unsigned *out_ep) {
    unsigned pos=0,n,active=0,interfaces=0,ep;
    *in_ep=*out_ep=0;
    if(len<9 || d[0]!=9 || d[1]!=2 || ts_le16(d+2)!=len) return 0;
    while(pos<len) {
        n=d[pos]; if(n<2 || n>len-pos) return 0;
        if(d[pos+1]==4) {
            if(n<9) return 0;
            active=d[pos+3]==0 && d[pos+5]==1 && d[pos+6]==3;
            if(active) interfaces++;
        } else if(d[pos+1]==5 && active) {
            if(n<7 || (d[pos+3]&3)!=2 || ts_le16(d+pos+4)!=64) return 0;
            ep=d[pos+2];
            if(!(ep&15) || (ep&0x70)) return 0;
            if(ep&0x80) { if(*in_ep) return 0; *in_ep=ep; }
            else { if(*out_ep) return 0; *out_ep=ep; }
        }
        pos+=n;
    }
    return interfaces==1 && *in_ep && *out_ep;
}
static void le32(unsigned char *p,unsigned long v) {
    unsigned i; for(i=0;i<4;i++) p[i]=(unsigned char)(v>>(8*i));
}
/* Only validated wrappers below construct commands. */
static unsigned tm_encode(const unsigned char *raw,unsigned size,unsigned char *out) {
    unsigned char sysex[72];unsigned crc,i,k,pos=0,n,len=12+2*size;
    crc=tm_crc(raw,size);memcpy(sysex,"\360\175TSK",5);sysex[5]=3;sysex[6]=0x20;
    for(i=0;i<size;i++){sysex[7+2*i]=raw[i]&127;sysex[8+2*i]=raw[i]>>7;}
    sysex[7+2*size]=crc&127;sysex[8+2*size]=(crc>>7)&1;
    sysex[9+2*size]=(crc>>8)&127;sysex[10+2*size]=crc>>15;sysex[len-1]=0xF7;
    for(i=0;i<len;i+=3) {
        n=len-i;if(n>3)n=3;out[pos++]=(unsigned char)(i+n<len?4:4+n);
        for(k=0;k<3;k++)out[pos++]=k<n?sysex[i+k]:0;
    }
    return pos;
}
static unsigned encode_command(unsigned long nonce,unsigned long seq,unsigned op,
                        unsigned profile,unsigned extended,unsigned long value,
                        const unsigned char mac[6],unsigned char out[76]) {
    unsigned char raw[22];
    memset(raw,0,sizeof(raw)); le32(raw,nonce);le32(raw+4,seq);
    raw[8]=(unsigned char)op;raw[9]=(unsigned char)profile;raw[10]=42;
    raw[11]=(unsigned char)extended;le32(raw+12,value);memcpy(raw+16,mac,6);
    return tm_encode(raw,22,out);
}
unsigned tm_command(unsigned long nonce,unsigned long seq,unsigned op,
                    unsigned profile,unsigned duration,const unsigned char mac[6],
                    unsigned char out[76]) {
    /* Retain the clock reader's restricted command set. */
    if(!nonce || !seq || profile!=4 ||
       (op!=1 && op!=2 && op!=3 && op!=8) ||
       (op==2?duration!=5:duration!=0)) return 0;
    return encode_command(nonce,seq,op,profile,0,duration,mac,out);
}
unsigned tm_ptp_command(unsigned long nonce,unsigned long seq,unsigned op,
                        unsigned profile,unsigned long generation,
                        unsigned char out[76],const unsigned char mac[6]) {
    unsigned extended;
    unsigned long value=0;
    if(!nonce || !seq || (profile!=1 && profile!=2 && profile!=3) ||
       (op!=1 && op!=2 && op!=3 && op!=4 && op!=5 && op!=6 && op!=8))return 0;
    if(op==4?!generation:generation!=0)return 0;
    extended=op==1 || op==2 || op==4;
    if(op==2)value=15;
    if(op==4)value=generation;
    if(op==5)value=4;
    return encode_command(nonce,seq,op,profile,extended,value,mac,out);
}
/* Decode signed little-endian integers without a 64-bit DOS compiler type.
   Form the magnitude before conversion, preserving small negative Q17 values. */
double tm_signed(const unsigned char *p,unsigned bytes) {
    unsigned char magnitude[8];unsigned i,v,carry=1,negative;
    double result=0;
    if(!bytes || bytes>8)return 0;
    negative=p[bytes-1]&128;
    for(i=0;i<bytes;i++) {
        v=negative?(unsigned)(p[i]^255)+carry:p[i];
        magnitude[i]=(unsigned char)v;carry=v>>8;
    }
    for(i=bytes;i>0;i--)result=result*256.0+magnitude[i-1];
    return negative?-result:result;
}
int tm_ptp_sample(const unsigned char raw[94],double *offset,double *delay,long *ppb) {
    unsigned i;double correction;
    if(raw[10]!=31 || raw[11]!=42 || !ts_le32(raw+12))return 0;
    if(ts_le32(raw+22)>=1000000000UL)return 0;
    /* t1..t4 nanoseconds are at 36,46,56,66 (clock is at 22). */
    for(i=36;i<=66;i+=10)if(ts_le32(raw+i)>=1000000000UL)return 0;
    *offset=tm_signed(raw+70,8)/131072.0;
    *delay=tm_signed(raw+78,8)/131072.0;
    correction=tm_signed(raw+86,4);
    if(*offset < -25000000.0 || *offset>25000000.0 || *delay<0 ||
       *delay>50000000.0 || correction < -100000.0 || correction>100000.0 ||
       !ts_le32(raw+90))return 0;
    *ppb=(long)correction;return 1;
}

unsigned tm_host_command(unsigned long nonce,unsigned long seq,long ppb,
                         unsigned long generation,unsigned long token,
                         unsigned char out[96],const unsigned char mac[6]) {
    unsigned char raw[30];
    if(!nonce||!seq||!generation||ppb < -100000L||ppb>100000L)return 0;
    memset(raw,0,sizeof(raw));le32(raw,nonce);le32(raw+4,seq);
    raw[8]=7;raw[9]=3;raw[10]=42;le32(raw+12,(unsigned long)ppb);
    memcpy(raw+16,mac,6);le32(raw+22,generation);le32(raw+26,token);
    return tm_encode(raw,30,out);
}
int tm_ack_matches(const tm_parser *p,unsigned long nonce,unsigned long seq,
                   unsigned op,const unsigned char mac[6]) {
    return p->version==3 && p->kind==0x21 && p->len==(op==8?64:op==7?44:32) &&
        ts_le32(p->raw)==nonce && ts_le32(p->raw+4)==seq && p->raw[8]==op &&
        !memcmp(p->raw+22,mac,6) && p->raw[28]==42;
}
/* Explicit two's-complement handling avoids implementation-defined casts. */
static long signed32(const unsigned char *p) {
    unsigned long u=ts_le32(p);
    return u&0x80000000UL?-(long)(0xFFFFFFFFUL-u)-1L:(long)u;
}
int tm_host_ack(const unsigned char *a,unsigned long generation,long requested) {
    unsigned long addend,expected,mag,change;
    if(requested < -100000L || requested>100000L)return 0;
    if(a[9]||a[10]!=2||a[11]!=3||ts_le32(a+12)||ts_le32(a+16)!=generation||
       a[29]!=95||a[30]||a[31]!=1||signed32(a+32)!=requested||ts_le32(a+40)>2000000000UL)return 0;
    /* floor(2^31 * abs(ppb) / 1e9), using 32-bit products only. */
    mag=(unsigned long)(requested<0?-requested:requested);
    /* 0.147483648 * mag; both products stay below 2^32. */
    change=2*mag+(mag/10000UL*147483648UL+
                  (mag%10000UL)*14748UL+(mag%10000UL)*3648UL/10000UL)/100000UL;
    expected=requested<0?0x80000000UL-change:0x80000000UL+change;
    addend=ts_le32(a+36);return addend==expected;
}
