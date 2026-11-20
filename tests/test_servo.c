#ifdef __BORLANDC__
#include "TESTDOS.H"
#else
#include <assert.h>
#endif
#ifndef __BORLANDC__
#include <math.h>
#endif
#include <stdlib.h>
#include <stdio.h>
#include "SERVO.H"

static void simulate(int kind,double drift,double start,int irregular) {
    pt_servo s;long applied=0,next=0;unsigned long ms=0;int i;
    double phase=start,dt,noise,rms=0;
    pt_servo_init(&s,kind);
    for(i=0;i<4000;i++) {
        dt=irregular?(i%3==0?0.2:i%3==1?0.3:0.25):0.25;
        ms+=(unsigned long)(dt*1000+0.5);phase+=(drift+applied)*dt;
        noise=(i%7-3)*4.0;
        assert(pt_servo_update(&s,phase+noise,ms,applied,&next));
        assert(next>=-100000L&&next<=100000L&&labs(next-applied)<=10000L);
        applied=next;
        if(i>=3600)rms+=phase*phase;
    }
    rms=sqrt(rms/400);
    printf("servo %d drift %.0f start %.0f irregular %d: final RMS %.2f ns\n",kind,drift,start,irregular,rms);
    assert(rms<100.0);assert(fabs(applied+drift)<150.0);
}
int main(void) {
    pt_servo s;long next;int kind,i;unsigned long ms;double phase;
    for(kind=1;kind<=5;kind++) {
        simulate(kind,16000L,400000L,0);simulate(kind,-23000L,-700000L,1);
        pt_servo_init(&s,kind);
        assert(pt_servo_update(&s,100,0xFFFFFF80UL,500,&next)&&next==500);
        assert(pt_servo_update(&s,101,122,500,&next)); /* 32-bit wrap */
        assert(pt_servo_update(&s,101,122,next,&next)); /* duplicate rebases */
        assert(pt_servo_update(&s,200,5000,1234,&next)&&next==1234);
        assert(!pt_servo_update(&s,25000001L,5250,0,&next));
        assert(!pt_servo_update(&s,0,5250,100001L,&next));
        /* Saturation, sudden phase step, gap then oscillator change. */
        pt_servo_init(&s,kind);next=0;ms=0;phase=20000000L;
        for(i=0;i<8000;i++) {
            if(i==2000)phase-=500000L;
            if(i==4000){ms+=5000;phase+=100000L;}
            phase+=((i<4000?50000L:-18000L)+next)*0.25;ms+=250;
            assert(pt_servo_update(&s,phase,ms,next,&next));
        }
        assert(fabs(phase)<200.0);
    }
    puts("PASS: all host servos, closed-loop drift/noise, slew limits, wrap, gaps and recovery.");
    return 0;
}
