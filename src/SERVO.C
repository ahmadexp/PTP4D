#include <string.h>
#include "SERVO.H"

static double bound(double v,double low,double high) {
    return v<low?low:v>high?high:v;
}
static double magnitude(double v){return v<0?-v:v;}
void pt_servo_init(pt_servo *s,int kind) {memset(s,0,sizeof(*s));s->kind=kind;s->level=2;}
static void anchor(pt_servo *s,double e,unsigned long ms,long applied) {
    int kind=s->kind;
    pt_servo_init(s,kind);s->ready=1;s->last_ms=ms;s->previous=e;
    s->integral=applied;s->phase=e;s->freq=-applied;
    s->p00=400.0;s->p11=1000000.0;s->anchor=e;
    s->n=1;s->x[0]=0;s->y[0]=e;
}
static double pi(pt_servo *s,double e,double dt,long applied) {
    double kp=0.5,ki=0.05,candidate,wanted,limited,oldkp;
    int level=s->level;
    if(s->kind==2) {
        s->count++;s->sum+=e;s->absolute+=magnitude(e);
        if(e*s->previous<0)s->reversals++;
        if(magnitude(e)>10000.0){s->level=2;s->quiet=0;}
        else if(s->count>=32) {
            if(magnitude(s->sum)>s->absolute*0.7 && s->absolute>3200.0) {
                if(s->level<2)s->level++;s->quiet=0;
            }else if(s->absolute<3200.0 || s->reversals>20) {
                if(++s->quiet>=2){if(s->level)s->level--;s->quiet=0;}
            }else s->quiet=0;
            s->count=s->reversals=0;s->sum=s->absolute=0;
        }
        kp=s->level==2?0.75:s->level==1?0.5:0.25;
        ki=s->level==2?0.10:s->level==1?0.05:0.02;
        oldkp=level==2?0.75:level==1?0.5:0.25;
        s->integral=bound(s->integral+(kp-oldkp)*e,-100000.0,100000.0);
    }
    candidate=bound(s->integral-ki*e*dt,-100000.0,100000.0);
    wanted=candidate-kp*e;
    limited=bound(wanted,bound(applied-10000.0,-100000.0,100000.0),
                          bound(applied+10000.0,-100000.0,100000.0));
    /* Do not accumulate in the direction of amplitude or slew saturation. */
    if(wanted==limited || (wanted-limited)*(-e)<0)s->integral=candidate;
    return s->integral-kp*e;
}
static double regression(pt_servo *s,double e,double dt,long applied) {
    double dx,dy,mx=0,my=0,xx=0,xy=0,slope,fit;int i;
    /* Slide and rebase both axes to bound history during indefinite runs. */
    if(s->n==8) {
        dx=s->x[1];dy=s->y[1];
        for(i=1;i<8;i++){s->x[i-1]=s->x[i]-dx;s->y[i-1]=s->y[i]-dy;}
        s->n=7;
    }
    i=s->n;s->x[i]=s->x[i-1]+dt;
    s->y[i]=s->y[i-1]+e-s->previous-applied*dt;s->n++;
    if(s->n<4)return applied;
    for(i=0;i<s->n;i++){mx+=s->x[i];my+=s->y[i];}
    mx/=s->n;my/=s->n;
    for(i=0;i<s->n;i++){dx=s->x[i]-mx;xx+=dx*dx;xy+=dx*(s->y[i]-my);}
    slope=xy/xx;
    fit=e+my+slope*(s->x[s->n-1]-mx)-s->y[s->n-1];
    s->freq=bound(slope,-100000.0,100000.0);
    return -s->freq-fit/4.0;
}
static double kalman(pt_servo *s,double e,double dt,long applied) {
    double a,b,c,k0,k1,innovation,r=400.0,q=4.0,v;
    s->phase+=(s->freq+applied)*dt;
    a=s->p00+2*dt*s->p01+dt*dt*s->p11+dt+q*dt*dt*dt/3;
    b=s->p01+dt*s->p11+q*dt*dt/2;c=s->p11+q*dt;
    k0=a/(a+r);k1=b/(a+r);innovation=e-s->phase;
    s->phase+=k0*innovation;s->freq=bound(s->freq+k1*innovation,-100000.0,100000.0);
    /* Joseph update keeps covariance nonnegative in software arithmetic. */
    v=1-k0;s->p00=v*v*a+k0*k0*r;
    s->p01=v*(b-k1*a)+k0*k1*r;
    s->p11=bound(c-2*k1*b+k1*k1*(a+r),0.001,1000000.0);
    return -s->freq-s->phase/4.0;
}
static double pllfll(pt_servo *s,double e,double dt,long applied) {
    double f;
    s->elapsed+=dt;s->control+=applied*dt;
    if(s->elapsed>=4.0) {
        f=bound((e-s->anchor-s->control)/s->elapsed,-100000.0,100000.0);
        s->freq=s->n==1?f:(s->freq+f)/2;s->n=2;
        s->elapsed=s->control=0;s->anchor=e;
    }
    return -s->freq-e/4.0;
}
int pt_servo_update(pt_servo *s,double e,unsigned long ms,long applied,long *command) {
    unsigned long elapsed;double dt,u;
    /* Comparisons also reject NaN on the native harness. */
    if(s->kind<1||s->kind>5 || !(e>=-25000000.0 && e<=25000000.0) ||
       applied < -100000L || applied>100000L)return 0;
    elapsed=(ms-s->last_ms)&0xFFFFFFFFUL;
    if(!s->ready||elapsed<100UL||elapsed>1500UL) {
        anchor(s,e,ms,applied);*command=applied;return 1;
    }
    dt=elapsed/1000.0;
    if(s->kind<=2)u=pi(s,e,dt,applied);
    else if(s->kind==3)u=regression(s,e,dt,applied);
    else if(s->kind==4)u=kalman(s,e,dt,applied);
    else u=pllfll(s,e,dt,applied);
    u=bound(u,-100000.0,100000.0);u=bound(u,applied-10000.0,applied+10000.0);
    *command=(long)(u<0?u-0.5:u+0.5);s->previous=e;s->last_ms=ms;return 1;
}
