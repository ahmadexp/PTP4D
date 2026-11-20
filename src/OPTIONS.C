#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include "OPTIONS.H"

static int same(const char *a,const char *b) {
    while(*a && *b) if(toupper((unsigned char)*a++)!=toupper((unsigned char)*b++))return 0;
    return !*a && !*b;
}
static int number(const char *s,int low,int high,int *out) {
    long n=0;int sign=1;
    if(*s=='-' || *s=='+'){if(*s=='-')sign=-1;s++;}
    if(!*s)return 0;
    while(*s){if(*s<'0'||*s>'9'||n>100000L)return 0;n=n*10+*s++-'0';}
    n*=sign;if(n<low||n>high)return 0;*out=(int)n;return 1;
}
const char *pt_servo_name(int s) {
    static const char *names[]={"PI","HOST_PI","AUTO_PI","LINREG","KALMAN","PLLFLL"};
    return s>=0&&s<6?names[s]:"invalid";
}
int pt_options_parse(int argc,char **argv,pt_options *o,const char **error) {
    int i,j,n,action=0,mode=0,sync=0,servo=0,epoch=0,scale=0,tai=0,dos=0,zone=0,valid=0,update=0,port=0;
    const char *a,*v;
    memset(o,0,sizeof(*o));o->role=1;o->port=-1;*error="Invalid or duplicate switch/value. Use /?.";
    for(i=1;i<argc;i++) {
        a=argv[i];
        if(same(a,"/?")||same(a,"/HELP"))return 2;
        if(same(a,"/DIAG")){if(o->diag)return 0;o->diag=1;continue;}
        if(same(a,"/CLOCK")||same(a,"/LIST")||same(a,"/HOST")||same(a,"/CARD")) {
            if(action++)return 0;
            o->action=same(a,"/CLOCK")?OPT_CLOCK:same(a,"/LIST")?OPT_LIST:same(a,"/HOST")?OPT_HOST:OPT_CARD;
            continue;
        }
        if(i+1>=argc)return 0;v=argv[++i];
        if(same(a,"/PTP")) {
            if(action++||!number(v,0,3600,&n)||(n&&n<10))return 0;
            o->action=OPT_PTP;o->seconds=(unsigned)n;
        }else if(same(a,"/MODE")) {
            if(mode++)return 0;
            if(same(v,"FOLLOWER"))o->role=1;
            else if(same(v,"GM"))o->role=2;else return 0;
        }else if(same(a,"/SERVO")) {
            if(servo++)return 0;
            for(j=0;j<6;j++)if(same(v,pt_servo_name(j)))break;
            if(j==6)return 0;o->servo=j;
        }else if(same(a,"/SYNC")) {
            if(sync++)return 0;
            if(same(v,"NONE"))o->sync=SYNC_NONE;
            else if(same(v,"PHC2DOS"))o->sync=SYNC_PHC_DOS;
            else if(same(v,"DOS2PHC"))o->sync=SYNC_DOS_PHC;else return 0;
        }else if(same(a,"/PORT")) {
            if(port++||!number(v,1,4,&n))return 0;o->port=n-1;
        }else if(same(a,"/EPOCH")) {if(epoch++||!same(v,"UNIX"))return 0;
        }else if(same(a,"/SCALE")) {
            if(scale++)return 0;
            if(same(v,"UTC"))o->scale=0;else if(same(v,"TAI"))o->scale=1;else return 0;
        }else if(same(a,"/TAIOFF")) {if(tai++||!number(v,0,100,&o->tai_offset))return 0;
        }else if(same(a,"/DOS")) {
            if(dos++)return 0;
            if(same(v,"UTC"))o->dos_local=0;else if(same(v,"LOCAL"))o->dos_local=1;else return 0;
        }else if(same(a,"/TZ")) {if(zone++||!number(v,-840,840,&o->zone_minutes))return 0;
        }else if(same(a,"/VALID")) {if(valid++||!number(v,10,3600,&n))return 0;o->valid_seconds=(unsigned)n;
        }else if(same(a,"/UPDATE")) {
            if(update++)return 0;
            if(same(v,"STEP"))o->track=0;else if(same(v,"TRACK"))o->track=1;else return 0;
        }else return 0;
    }
    if(mode && !action)o->action=OPT_PTP;
    if(o->action!=OPT_PTP && (mode||servo||sync||epoch||scale||tai||dos||zone||valid||update))return 0;
    if(o->role==2 && !sync)o->sync=SYNC_DOS_PHC;
    if(o->role==2 && (servo||o->sync==SYNC_PHC_DOS)) {
        *error="GM cannot run a follower servo or copy PHC time into DOS.";return 0;
    }
    if(o->sync==SYNC_DOS_PHC) {
        *error="DOS2PHC unavailable: firmware clock writes require Ethernet-off profile 4. GM profile 2 cannot accept DOS time. /MODE GM /SYNC NONE is free-running only.";return 0;
    }
    if(o->sync==SYNC_PHC_DOS) {
        if(!epoch||!scale||!dos||!valid||tai!=o->scale||zone!=o->dos_local) {
            *error="PHC2DOS needs /EPOCH UNIX /SCALE UTC|TAI /DOS UTC|LOCAL /VALID 10..3600; TAI needs /TAIOFF, LOCAL needs /TZ minutes.";return 0;
        }
    }else if(epoch||scale||tai||dos||zone||valid||update) {
        *error="Calendar and update switches require /SYNC PHC2DOS.";return 0;
    }
    if((o->action==OPT_HOST||o->action==OPT_CARD)&&(port||o->diag))return 0;
    return 1;
}
void pt_help(void) {
    puts("Usage: PTP4D [/PTP seconds] [/MODE FOLLOWER|GM] [/PORT 1..4]");
    puts("  /SERVO PI|HOST_PI|AUTO_PI|LINREG|KALMAN|PLLFLL (follower only)");
    puts("  /SYNC NONE|PHC2DOS|DOS2PHC   PI and NONE are legacy defaults.");
    puts("  /MODE implies /PTP 0. Durations: 0 or 10..3600. ESC stops.");
    puts("  GM defaults to DOS2PHC, which current firmware cannot support.");
    puts("  /MODE GM /SYNC NONE: raw, free-running fixed-peer source only.");
    puts("  PHC2DOS requires /EPOCH UNIX /SCALE UTC|TAI /DOS UTC|LOCAL");
    puts("    /TAIOFF 0..100 with TAI; /TZ -840..840 with LOCAL (DOS-UTC).");
    puts("    /VALID 10..3600 asserts a valid source and no leap/DST change");
    puts("    for that many seconds. No automatic UTC/leap quality is available.");
    puts("    /UPDATE STEP (one startup set, default) or TRACK (30s checks).");
    puts("    DOS date/time setters may also update the battery RTC.");
    puts("  /CLOCK: temporary hardware-only read; no arguments: passive read.");
    puts("  /LIST, /DIAG, /HOST or /CARD retain their original meanings.");
    puts("Advanced servos require profile 3/op 7; no silent PI fallback.");
}
