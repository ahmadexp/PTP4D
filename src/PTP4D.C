/* PTP4D: AX88279A identification/clock probe for real-mode DOS.
 * Uses stock PicoPCMCIA v0.22 USB pass-through. /CLOCK enables a five-second
 * clock-only session. /PTP runs the firmware PI follower under a renewable lease.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dos.h>
#include <bios.h>
#include "TSWIRE.H"
#include "TSMIDI.H"

static unsigned seg;
static int held, recovery;
static unsigned char buffer[TS_MAX];
static char detail[4][180];
static char clocks[2][16];
static unsigned long nanos[2];
static unsigned char samples[2][12];
static int sample_valid[2], selected = -1, matches, error;
static unsigned selected_gen;
static char diagnostics[8][240];
static tm_parser midi;
static unsigned ep_in, ep_out, frames, heartbeats, flags;
static unsigned long generation, sample_generation, ack_generation, started_generation;
static unsigned char mac[6], command_bytes[76];
static unsigned long nonce, sequence, last_sample_seq;
static int sample_count, clock_started, clock_stopped, ack_result=-1, captured;
static unsigned ack_phase, ack_profile, ack_restored, ack_armed;
#define PTP_RECORDS 128u
static unsigned char ptp_records[PTP_RECORDS][94];
static unsigned ptp_used,ptp_next,ptp_sync,ptp_delay,ptp_mode,ptp_seconds;
static unsigned long ptp_exchanges,ptp_renewals,ptp_last_tick;
static int ptp_started,ptp_stopped,ptp_escaped;
static void collect_ptp(void);
static int ptp_run(void);
static void ptp_report(void);
static unsigned long ack_error;


unsigned ts_rd(unsigned off) {
    return *(volatile unsigned far *)MK_FP(seg, off);
}
void ts_wr(unsigned off, unsigned value) {
    *(volatile unsigned far *)MK_FP(seg, off) = value;
}
unsigned char ts_rd8(unsigned off) {
    return *(volatile unsigned char far *)MK_FP(seg, off);
}
void ts_wr8(unsigned off, unsigned char value) {
    *(volatile unsigned char far *)MK_FP(seg, off) = value;
}
unsigned long ts_ticks(void) {
    unsigned long a, b;
    do {
        a = *(volatile unsigned long far *)MK_FP(0x40, 0x6C);
        b = *(volatile unsigned long far *)MK_FP(0x40, 0x6C);
    } while (a != b);
    return a;
}
void ts_poll(void) { }
static unsigned mux(unsigned fn) {
    union REGS r;
    memset(&r, 0, sizeof(r));
    r.x.ax = 0xE300u | fn;
    int86(0x2F, &r, &r);
    return r.h.al;
}
static int wait_value(unsigned off, unsigned value) {
    unsigned long start = ts_ticks(), spins = 0;
    while (ts_rd(off) != value) {
        if (ts_elapsed(start) > 91UL || ++spins > 4000000UL) return 0;
    }
    return 1;
}
static void post(unsigned off, unsigned value) {
    ts_wr8(off + 1, (unsigned char)(value >> 8));
    ts_wr8(off, (unsigned char)value);
}
static int quiet(void) {
    unsigned i;
    /* Do not overlap an existing USB, disk, config or CD command. */
    if (ts_rd(0x04D0) || ts_rd(0x04DA) || ts_rd(0x04C8) ||
        ts_rd(0x04C4) || ts_rd(TS_GCTRL) || ts_rd(0x0F26) ||
        ts_rd(0x0ED0) || ts_rd(0x0EDC) == 1) return 0;
    for (i = 0; i < 4; i++)
        if (ts_rd(TS_SLOT + 32u*i) || ts_rd(TS_SLOT + 32u*i + 4) == 1) return 0;
    /* Stop the resident from touching shared staging while this tool owns it.
       COMrade uses the PC110 serial UART independently and remains available. */
    if (mux(1) != 255) return 0;
    held = 1;
    ts_wr(0x0F28, 1); /* SD busy sentinel, then STOP; invalidates prefetch */
    post(0x0F26, 7);
    if (!wait_value(0x0F26, 0) || !wait_value(0x0F28, 2)) return 0;
    ts_wr(0x0EDC, 2); /* native CD stream STOP */
    post(0x0ED0, 3);
    if (!wait_value(0x0ED0, 0) || !wait_value(0x0EDC, 0)) return 0;
    return 1;
}
static int reset_usb(void) {
    unsigned old = ts_rd(TS_STATE) >> 8;
    unsigned tag = ((ts_rd(TS_GDONE) >> 8) + 1u) & 255u;
    unsigned command = (tag << 8) | 1u;
    unsigned long start;
    post(TS_GCTRL, command);
    if (!wait_value(TS_GDONE, command)) return 0;
    start = ts_ticks();
    /* An aborted EP0 may still write its data. Do not reuse staging until
       the stack has detached the old generation, after its command ACK. */
    while ((ts_rd(TS_STATE) >> 8) == old || ts_rd(TS_SLOT + 4) == 1) {
        if (ts_elapsed(start) > 91UL) return 0;
    }
    return 1;
}
static int get(unsigned port, unsigned gen, unsigned type, unsigned req,
               unsigned val, unsigned idx, unsigned len, unsigned *actual) {
    int r = ts_control(port, gen, type, req, val, idx, len, buffer, actual);
    if (r == TS_TIMEOUT) {
        recovery = !reset_usb();
        error = r;
    }
    return r;
}
static void string_desc(unsigned port, unsigned gen, unsigned index,
                        unsigned lang, char *out) {
    unsigned n, i, limit;
    out[0] = 0;
    if (!index || error) return;
    if (get(port, gen, 0x80, 6, 0x0300u | index, lang, 64, &n) != TS_OK) return;
    if (n < 2 || buffer[1] != 3 || buffer[0] < 2 || (buffer[0] & 1)) return;
    limit = buffer[0] < n ? buffer[0] : n;
    for (i = 2; i + 1 < limit && i < 64; i += 2)
        out[i/2 - 1] = (!buffer[i+1] && buffer[i] >= 32 && buffer[i] < 127)
                       ? buffer[i] : '?';
    out[i/2 - 1] = 0;
}
static void scan(int wanted) {
    unsigned port, ps, gen, n, vid, pid, bcd, product, serial, lang;
    char name[32], number[32];
    int r, candidate;
    for (port = 0; port < 4; port++) {
        ps = ts_rd(TS_PORTS + port*2);
        if (!(ps & 2)) continue;
        if (ps & 4) { sprintf(detail[port], "Port %u: low-speed device (not AX88279A)", port+1); continue; }
        gen = ps >> 8;
        r = get(port, gen, 0x80, 6, 0x0100, 0, 18, &n);
        if (r != TS_OK || n != 18 || buffer[0] != 18 || buffer[1] != 1) {
            sprintf(detail[port], "Port %u: device descriptor failed (%d, %u bytes)", port+1, r, n);
            if (error) return;
            continue;
        }
        candidate = ts_ax279a(buffer, n);
        vid = ts_le16(buffer+8); pid = ts_le16(buffer+10); bcd = ts_le16(buffer+12);
        product = buffer[15]; serial = buffer[16];
        name[0] = number[0] = 0;
        lang = 0;
        if (get(port, gen, 0x80, 6, 0x0300, 0, 64, &n) == TS_OK &&
            n >= 4 && buffer[1] == 3 && buffer[0] >= 4) lang = ts_le16(buffer+2);
        if (lang) {
            string_desc(port, gen, product, lang, name);
            string_desc(port, gen, serial, lang, number);
        }
        sprintf(detail[port], "Port %u: %04X:%04X rev %04X%s\n  Product: %s\n  Serial: %s",
                port+1, vid, pid, bcd, candidate ? " AX88279A candidate" : "",
                name[0] ? name : "(not reported)", number[0] ? number : "(not reported)");
        if (candidate && (wanted < 0 || wanted == (int)port)) {
            matches++;
            selected = (int)port; selected_gen = gen;
        }
        if (error) return;
    }
}
static int bulk(unsigned ep, unsigned len, unsigned char *data, unsigned *actual) {
    int r=ts_bulk((unsigned)selected,selected_gen,ep,len,data,actual);
    if(r==TS_TIMEOUT) { recovery=!reset_usb(); error=r; }
    return r;
}
static int midi_setup(void) {
    unsigned n,total; int r;
    r=get((unsigned)selected,selected_gen,0x80,6,0x0200,0,9,&n);
    if(r!=TS_OK || n!=9) return r==TS_OK?TS_SHORT:r;
    total=ts_le16(buffer+2);
    if(total>TS_MAX || total<9) return TS_INVALID;
    r=get((unsigned)selected,selected_gen,0x80,6,0x0200,0,total,&n);
    if(r!=TS_OK) return r;
    if(!tm_endpoints(buffer,n,&ep_in,&ep_out)) return TS_INVALID;
    r=get((unsigned)selected,selected_gen,0xC0,1,0x10,6,6,&n);
    if(r!=TS_OK || n!=6) return r==TS_OK?TS_SHORT:r;
    memcpy(mac,buffer,6);
    sprintf(diagnostics[0],"USB MIDI: IN %02X, OUT %02X, 64-byte packets",ep_in,ep_out);
    sprintf(diagnostics[1],"MAC: %02X:%02X:%02X:%02X:%02X:%02X",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    return TS_OK;
}
static void save_stamp(const unsigned char *stamp) {
    unsigned i;
    if(sample_count>=2) return;
    i=(unsigned)sample_count;
    memcpy(samples[i],stamp+6,4);memcpy(samples[i]+4,stamp,6);
    samples[i][10]=samples[i][11]=0;
    sample_valid[i]=ts_clock(samples[i],12,clocks[i],&nanos[i]);
    if(sample_valid[i]) sample_count++;
}
static void telemetry(void) {
    unsigned long seq;
    if(midi.len!=94 || !((midi.version==2 && midi.kind==0x10) ||
       (midi.version==3 && midi.kind==0x22)) || memcmp(midi.raw+4,mac,6) ||
       midi.raw[11]!=42) return;
    flags=midi.raw[10];generation=ts_le32(midi.raw+12);heartbeats++;
    if((midi.kind==0x10 && flags!=0 && flags!=1 && flags!=3 && flags!=31) ||
       (midi.kind==0x22 && flags>15)) return;
    if(ptp_mode)collect_ptp();
    seq=ts_le32(midi.raw);
    if(sample_count && sample_generation!=generation) {
        sample_count=0;sample_valid[0]=sample_valid[1]=0;
    }
    if((flags&1) && (!sample_count || seq!=last_sample_seq)) {
        sample_generation=generation;
        save_stamp(midi.raw+16);last_sample_seq=seq;
    }
}
/* Receive whole frames across any USB packet boundary. An ACK is accepted only
   when nonce, sequence, opcode, MAC, domain, framing and CRC all match. */
static int receive(unsigned op,unsigned long ticks_limit) {
    unsigned n,i; int r; unsigned long start=ts_ticks();
    do {
        r=bulk(ep_in,64,buffer,&n);
        if(r!=TS_OK) return r;
        if(n&3) return TS_SHORT;
        for(i=0;i<n;i+=4) if(tm_event(&midi,buffer+i)) {
            frames++;telemetry();
            if(op && midi.version==3 && midi.kind==0x21 &&
               midi.len==(op==8?64:32) && ts_le32(midi.raw)==nonce &&
               ts_le32(midi.raw+4)==sequence && midi.raw[8]==op &&
               !memcmp(midi.raw+22,mac,6) && midi.raw[28]==42) {
                ack_result=midi.raw[9];ack_phase=midi.raw[10];ack_profile=midi.raw[11];
                ack_error=ts_le32(midi.raw+12);ack_generation=ts_le32(midi.raw+16);ack_restored=midi.raw[30];ack_armed=midi.raw[31];
                return TS_OK;
            }
        }
        if(!op && !ptp_mode && sample_count>=2) return TS_OK;
    } while(ts_elapsed(start)<ticks_limit);
    return op?TS_SHORT:TS_OK;
}
static int command(unsigned op,unsigned duration) {
    unsigned n,actual,offset,part;int r;
    sequence++;ack_result=-1;
    n=tm_command(nonce,sequence,op,4,duration,mac,command_bytes);
    if(!n) return TS_INVALID;
    for(offset=0;offset<n;offset+=part) {
        part=n-offset;if(part>64)part=64;
        r=bulk(ep_out,part,command_bytes+offset,&actual);
        if(r!=TS_OK || actual!=part) return r==TS_OK?TS_SHORT:r;
    }
    return receive(op,55UL);
}
static int read_midi(int enable) {
    int r,stop_result;
    r=midi_setup();if(r!=TS_OK)return r;
    r=receive(0,37UL);if(r!=TS_OK || sample_count>=2 || !enable)return r;
    if(!heartbeats) return TS_SHORT;
    nonce=(ts_ticks()^ts_le32(mac+2)^0x54530000UL)&0xFFFFFFFFUL;
    if(!nonce)nonce=1;
    r=command(1,0);
    if(r!=TS_OK || ack_result || ack_error || ack_armed || !ack_restored) return r==TS_OK?TS_BUSY:r;
    r=command(2,5);
    if(r!=TS_OK || ack_result) return r==TS_OK?TS_INVALID:r;
    clock_started=1;started_generation=ack_generation;
    sprintf(diagnostics[2],"Clock start ACK: result %d, phase %u, profile %u, error %lu, armed %u",ack_result,ack_phase,ack_profile,ack_error,ack_armed);
    r=receive(0,37UL);
    if(r==TS_OK) {
        /* Verify a request/response clock capture as well as telemetry. */
        r=command(8,0);
        sprintf(diagnostics[3],"Clock capture ACK: USB %d, result %d, phase %u, profile %u, error %lu, armed %u",r,ack_result,ack_phase,ack_profile,ack_error,ack_armed);
        if(r==TS_OK && !ack_result && !ack_error && ack_phase==2 &&
           ack_profile==4 && ack_armed && ack_generation==started_generation &&
           midi.raw[29]==127 && ts_le32(midi.raw+60)==3UL) {
            sample_count=0;sample_valid[0]=sample_valid[1]=0;
            save_stamp(midi.raw+32);save_stamp(midi.raw+42);
            if(sample_count!=2)r=TS_SHORT; else captured=1;
        } else if(r==TS_OK)r=TS_INVALID;
    }
    /* A five-second lease also expires if transport fails before STOP. */
    if(!error && !recovery) {
        stop_result=command(3,0);
        clock_stopped=stop_result==TS_OK && !ack_result && !ack_error && ack_restored && !ack_armed;
        if(!clock_stopped && r==TS_OK)r=stop_result==TS_OK?TS_INVALID:stop_result;
    }
    return r;
}
static void bios_text(const char *s) {
    union REGS r;
    while(*s) {
        memset(&r,0,sizeof(r));r.h.ah=0x0E;r.h.al=(unsigned char)*s++;
        r.x.bx=7;int86(0x10,&r,&r);
    }
}
static void collect_ptp(void) {
    double offset,delay;long ppb;unsigned sync,dseq;char line[100];
    if(!ptp_started || generation!=started_generation || midi.version!=2 ||
       midi.kind!=0x10 || !tm_ptp_sample(midi.raw,&offset,&delay,&ppb))return;
    sync=ts_le16(midi.raw+26);dseq=ts_le16(midi.raw+28);
    if(ptp_exchanges && sync==ptp_sync && dseq==ptp_delay)return;
    ptp_sync=sync;ptp_delay=dseq;ptp_last_tick=ts_ticks();ptp_exchanges++;
    memcpy(ptp_records[ptp_next],midi.raw,94);
    ptp_next=(ptp_next+1)%PTP_RECORDS;if(ptp_used<PTP_RECORDS)ptp_used++;
    sprintf(line,"PTP4D %lu: offset %.1f ns, delay %.1f ns, rate %ld ppb\r\n",ptp_exchanges,offset,delay,ppb);
    bios_text(line);
}
static int ptp_command(unsigned op) {
    unsigned n,actual,offset,part;int r;
    sequence++;ack_result=-1;
    n=tm_ptp_command(nonce,sequence,op,1,op==4?started_generation:0,command_bytes,mac);
    if(!n)return TS_INVALID;
    for(offset=0;offset<n;offset+=part) {
        part=n-offset;if(part>64)part=64;
        r=bulk(ep_out,part,command_bytes+offset,&actual);
        if(r!=TS_OK || actual!=part)return r==TS_OK?TS_SHORT:r;
    }
    return receive(op,55UL);
}
static int ptp_run(void) {
    int r,stopped;unsigned long begin,renew;unsigned key;
    r=midi_setup();if(r!=TS_OK)return r;
    nonce=(ts_ticks()^ts_le32(mac+2)^0x50540000UL)&0xFFFFFFFFUL;
    if(!nonce)nonce=1;
    r=ptp_command(1);
    if(r!=TS_OK || ack_result || ack_armed)return r==TS_OK?TS_BUSY:r;
    if(ack_error==2 && ack_restored) {r=ptp_command(3);if(r!=TS_OK)return r;}
    if(ack_result || ack_error || !ack_restored || (midi.raw[29]&7)!=7)return TS_INVALID;
    r=ptp_command(5);if(r!=TS_OK || ack_result || ack_error)return r==TS_OK?TS_INVALID:r;
    ptp_started=1; /* STOP even when START's ACK is lost */
    r=ptp_command(2);started_generation=ack_generation;
    if(r==TS_OK && (ack_result || ack_error || !ack_armed || ack_profile!=1 || !started_generation))r=TS_INVALID;
    begin=renew=ts_ticks();
    while(r==TS_OK && (!ptp_seconds || ts_elapsed(begin)<(unsigned long)ptp_seconds*182UL/10UL)) {
        r=receive(0,2UL);
        if(r!=TS_OK)break;
        if(bioskey(1)) {key=(unsigned)bioskey(0);if((key&255)==27){ptp_escaped=1;break;}}
        if(ts_elapsed(renew)>=73UL) {
            r=ptp_command(4);renew=ts_ticks();
            if(r==TS_OK && (ack_result || ack_error || !ack_armed || ack_profile!=1 || ack_generation!=started_generation))r=TS_INVALID;
            if(r==TS_OK)ptp_renewals++;
        }
        if(ptp_exchanges && ts_elapsed(ptp_last_tick)>91UL) {r=TS_SHORT;break;}
    }
    if(!error && !recovery) {
        stopped=ptp_command(3);
        ptp_stopped=stopped==TS_OK && !ack_result && !ack_error && ack_restored && !ack_armed;
        if(!ptp_stopped && r==TS_OK)r=stopped==TS_OK?TS_INVALID:stopped;
    }
    return r;
}
static void ptp_report(void) {
    unsigned i,j,index,start;unsigned char raw[12];char sec[16];unsigned long ns;
    double offset,delay;long ppb;
    printf("PTP exchanges: %lu, lease renewals: %lu, stopped: %s%s\n",ptp_exchanges,ptp_renewals,
        ptp_stopped?"verified":"not verified",ptp_escaped?", ESC":"");
    if(!ptp_stopped && ptp_started)puts("Device lease expires within 15 seconds without renewal.");
    printf("Last ACK: result %d, phase %u, profile %u, error %lu, armed %u, restored %u\n",ack_result,ack_phase,ack_profile,ack_error,ack_armed,ack_restored);
    if(!ptp_exchanges)puts("No valid PTP exchanges observed.");
    puts("PTP_CSV,sync,delay_seq,offset_ns,path_delay_ns,rate_ppb,t1,t2,t3,t4");
    start=ptp_used==PTP_RECORDS?ptp_next:0;
    for(i=0;i<ptp_used;i++) {
        index=(start+i)%PTP_RECORDS;
        if(!tm_ptp_sample(ptp_records[index],&offset,&delay,&ppb))continue;
        printf("PTP_CSV,%u,%u,%.6f,%.6f,%ld",ts_le16(ptp_records[index]+26),ts_le16(ptp_records[index]+28),offset,delay,ppb);
        for(j=0;j<4;j++) {
            memcpy(raw,ptp_records[index]+36+j*10,4);memcpy(raw+4,ptp_records[index]+30+j*10,6);raw[10]=raw[11]=0;
            if(ts_clock(raw,12,sec,&ns))printf(",%s.%09lu",sec,ns);
        }
        puts("");
    }
    puts("PTP disciplines the attached TimeStick hardware clock. DOS wall time is unchanged.");
}
static const char *result_name(int r) {
    switch (r) {
    case TS_TIMEOUT: return "USB timeout; bus reset requested";
    case TS_BUSY: return "USB mailbox or TimeStick session busy";
    case TS_GONE: return "device disconnected or replaced";
    case TS_SHORT: return "short or malformed response";
    case TS_INVALID: return "invalid request or response";
    case 3: return "USB request stalled";
    case 4: return "USB transfer error";
    case 5: return "USB transfer timeout";
    case 6: return "USB device absent";
    default: return "request failed";
    }
}
static int identify_card(void) {
    FILE *saved;
    union REGS r;
    saved = fopen("C:\\PICOCARD\\SWDSTATE.BIN", "rb");
    if (saved) {
        fclose(saved);
        puts("SWD saved state exists. Resolve it with PICOCARD before using PTP4D.");
        return 0;
    }
    memset(&r, 0, sizeof(r)); r.x.ax = 0x1600;
    int86(0x2F, &r, &r);
    if (r.h.al && r.h.al != 0x80) { puts("Run PTP4D in real-mode DOS, outside Windows."); return 0; }
    if (mux(0) != 255) { puts("PICOCARD resident driver is not loaded."); return 0; }
    memset(&r, 0, sizeof(r)); r.x.ax = 0xE306;
    int86(0x2F, &r, &r);
    seg = r.x.bx;
    if (r.h.al != 255 || seg < 0xA000 || seg > 0xEE00) {
        puts("PICOCARD did not provide a valid memory window."); return 0;
    }
    printf("PicoPCMCIA window %04X, firmware v%u.%u, protocol %u\n",
           seg, ts_rd(0x0388), ts_rd(0x038A), ts_rd(0x0386));
    if (ts_rd(0x0386) != 2 || ts_rd(0x0388) != 0 || ts_rd(0x038A) != 22) {
        puts("This build requires firmware v0.22 and its matching PICOCARD driver."); return 0;
    }
    if (ts_rd(0x04E0) != 0xA55A) { puts("PicoPCMCIA startup is incomplete."); return 0; }
    return 1;
}
int main(int argc, char **argv) {
    unsigned i;
    int mode = -1, list = 0, diag = 0, enable = 0, wanted = -1, r = 0;
    puts("PTP4D 0.4 - TimeStick hardware PTP for DOS");
    for (i = 1; i < (unsigned)argc; i++) {
        if (!stricmp(argv[i], "/HOST")) mode = 1;
        else if (!stricmp(argv[i], "/CARD")) mode = 0;
        else if (!stricmp(argv[i], "/LIST")) list = 1;
        else if (!stricmp(argv[i], "/DIAG")) diag = 1;
        else if (!stricmp(argv[i], "/CLOCK")) enable = 1;
        else if (!stricmp(argv[i], "/PTP") && i+1<(unsigned)argc) {
            char *end; unsigned long seconds;
            i++;seconds=strtoul(argv[i],&end,10);
            if(!argv[i][0] || *end || seconds>3600UL || (seconds && seconds<10UL))goto usage;
            ptp_mode=1;ptp_seconds=(unsigned)seconds;
        }
        else if (!stricmp(argv[i], "/PORT") && i+1 < (unsigned)argc) {
            i++;
            if (strlen(argv[i]) != 1 || argv[i][0] < '1' || argv[i][0] > '4') goto usage;
            wanted = argv[i][0] - '1';
        } else goto usage;
    }
    if(ptp_mode && (enable || list || mode>=0))goto usage;
    if (!identify_card()) return 2;
    if(ptp_mode)puts("PTP follower, domain 42. ESC stops. Hardware clock only; DOS time is unchanged.");
    if (mode < 0 && !(ts_rd(TS_STATE) & 1)) {
        puts("Enable USB pass-through with PTP4D /HOST, then connect the TimeStick.");
        puts("This assigns all USB devices to the host; PTP4D /CARD restores card ownership.");
        return 2;
    }
    if (mode < 0 && (ts_rd(0x04C6) & 255) != 1) {
        puts("USB port is not in host role. Disconnect the programming computer,");
        puts("connect TimeStick, then run PICOCARD /USB to re-probe the port."); return 2;
    }
    if (!quiet()) { r = 3; goto finish; }
    if (mode >= 0) {
        if ((ts_rd(TS_STATE) & 1) != (unsigned)mode) {
            post(0x04C8, 3u | ((unsigned)mode << 8));
            if (!wait_value(0x04C8, 0) || (ts_rd(TS_STATE) & 1) != (unsigned)mode) r = 3;
        }
        goto finish;
    }
    scan(wanted);
    if (error) { r = 4; goto finish; }
    if (list) goto finish;
    if (matches != 1) { r = 5; goto finish; }
    error=ptp_mode?ptp_run():read_midi(enable);
    if(error!=TS_OK)r=4;
    else { error=0; if(ptp_mode?!ptp_exchanges:sample_count<2)r=6; }

finish:
    /* No DOS file/console I/O while the redirector and card IRQ are disarmed. */
    if (held && !recovery) { mux(2); held = 0; }
    if (recovery) puts("USB recovery failed. PICOCARD remains disarmed. Reboot DOS before using it.");
    for (i = 0; i < 4; i++) if (detail[i][0]) puts(detail[i]);
    for (i = 0; i < 8; i++) if (diagnostics[i][0]) puts(diagnostics[i]);
    if (list && !(ts_rd(TS_STATE) & 2)) puts("No USB devices enumerated on the pass-through ports.");
    if (mode >= 0 && !r) printf("USB ownership: %s (saved).\n", mode ? "host pass-through" : "card-managed");
    else if (r == 3) puts("Cannot acquire or change USB/staging ownership. No clock read performed.");
    else if (r == 5) puts(matches ? "Multiple AX88279A devices. Select one with /PORT 1..4." :
                                  "No matching AX88279A found (0B95:1790, bcdDevice 0500).");
    if (r == 4) printf("Clock probe failed: %s (%d).\n", result_name(error), error);
    if(ptp_mode) { ptp_report();return r; }
    for (i = 0; i < 2; i++) if (sample_valid[i])
        printf("Clock %u: %s.%09lu seconds\n", i+1, clocks[i], nanos[i]);
    if(heartbeats || diag) printf("MIDI frames: %u, heartbeats: %u, flags: %02X, generation: %lu\n",frames,heartbeats,flags,generation);
    if(r==6) puts(enable ? "Clock-only initialization did not produce valid samples." :
        "TimeStick responds, but its hardware clock is inactive. Use /CLOCK for a brief clock-only read.");
    if(clock_started) printf("Temporary clock-only session: %s.\n",clock_stopped?"stopped and restoration verified":"five-second lease will expire");
    if(ack_result>=0 && (diag || r)) printf("Last ACK: result %d, phase %u, profile %u, error %lu, restored %u, armed %u\n",ack_result,ack_phase,ack_profile,ack_error,ack_restored,ack_armed);
    if(captured) puts("Clock samples: command receipt and reply hardware snapshots.");
    if (sample_valid[1]) {
        puts(memcmp(samples[0], samples[1], 10) ? "Clock changed between reads." : "Clock did not advance between reads.");
        puts("Raw hardware-clock time; epoch, timescale and synchronization are unverified.");
    }
    return r;
usage:
    puts("Usage: PTP4D [/LIST | /DIAG | /CLOCK | /PTP seconds] [/PORT 1..4] | /HOST | /CARD");
    puts("Default: passive MIDI clock read. /CLOCK briefly enables the local counter.");
    puts("/PTP 10..3600: timed follower; /PTP 0: continuous until ESC. Start peer first.");
    return 1;
}
