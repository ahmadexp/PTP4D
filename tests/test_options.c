#ifdef __BORLANDC__
#include "TESTDOS.H"
#else
#include <assert.h>
#endif
#include <stdio.h>
#include <string.h>
#include "OPTIONS.H"
static pt_options o;
static const char *error;
static int parse(const char *line) {
    char text[600],*argv[40],*p;int n=1;
    strcpy(text,line);argv[0]="PTP4D";
    p=strtok(text," ");while(p){argv[n++]=p;p=strtok(0," ");}
    return pt_options_parse(n,argv,&o,&error);
}
int main(void) {
    const char *bad[]={"/PTP","/PTP 1","/PTP -1","/PTP 3601","/PTP 0 junk",
        "/PTP 0 /CLOCK","/HOST /PTP 0","/MODE FOLLOWER /LIST","/PTP 0 /SERVO WHAT",
        "/PTP 0 /SERVO PI /SERVO LINREG","/MODE GM /SERVO PI /SYNC NONE",
        "/MODE GM /SYNC PHC2DOS","/MODE FOLLOWER /SYNC DOS2PHC","/MODE GM",
        "/MODE GM /SYNC DOS2PHC","/MODE FOLLOWER /SYNC PHC2DOS",
        "/PTP 0 /SCALE UTC","/HOST /PORT 1","/PORT 5","/CLOCK /CLOCK",
        "/PTP 0 /SYNC PHC2DOS /EPOCH UNIX /SCALE TAI /DOS UTC /VALID 60",
        "/PTP 0 /SYNC PHC2DOS /EPOCH UNIX /SCALE UTC /DOS LOCAL /VALID 60",
        "/PTP 0 /SYNC PHC2DOS /EPOCH UNIX /SCALE UTC /TAIOFF 37 /DOS UTC /VALID 60"};
    unsigned i;char cmd[100];
    assert(parse("")==1&&o.action==OPT_PASSIVE);
    assert(parse("/?")==2);
    assert(parse("/PTP 60")==1&&o.servo==0&&o.sync==0&&o.role==1&&o.seconds==60);
    assert(parse("/MODE GM /SYNC NONE")==1&&o.role==2&&o.sync==0);
    assert(parse("/CLOCK /PORT 4 /DIAG")==1&&o.port==3&&o.diag);
    assert(parse("/MODE FOLLOWER /SYNC PHC2DOS /EPOCH UNIX /SCALE TAI /TAIOFF 37 /DOS LOCAL /TZ -480 /VALID 60 /UPDATE TRACK")==1);
    assert(o.scale&&o.tai_offset==37&&o.zone_minutes==-480&&o.track);
    for(i=0;i<6;i++){strcpy(cmd,"/ptp 0 /servo ");strcat(cmd,pt_servo_name((int)i));assert(parse(cmd)==1&&o.servo==(int)i);}
    for(i=0;i<sizeof(bad)/sizeof(*bad);i++){if(parse(bad[i]))printf("unexpected valid: %s\n",bad[i]);assert(!parse(bad[i]));}
    puts("PASS: CLI defaults, roles, every servo, conflicts, unsupported directions and civil-time prerequisites.");return 0;
}
