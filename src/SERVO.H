#ifndef SERVO_H
#define SERVO_H
/* Independent C89 controllers. Phase ns, frequency ppb, elapsed master ms.
   No absolute epoch in floating point, heap, or compiler 64-bit integers. */
typedef struct {
    int kind, ready, n, level, count, reversals, quiet;
    unsigned long last_ms;
    double integral, previous, sum, absolute, phase, freq;
    double p00, p01, p11;
    double x[8], y[8], elapsed, control, anchor;
} pt_servo;
void pt_servo_init(pt_servo *s,int kind);
/* Returns 0 for invalid input. A first sample or gap holds applied frequency. */
int pt_servo_update(pt_servo *s,double offset,unsigned long ms,long applied,long *command);
#endif
