/* Minimal test assertions for compiler installations with reduced headers. */
#ifndef TESTDOS_H
#define TESTDOS_H
#include <stdio.h>
#include <stdlib.h>
static void test_failed(const char *file,int line,const char *expression) {
    printf("Assertion failed: %s:%d: %s\n",file,line,expression);exit(1);
}
#define assert(x) ((x)?(void)0:test_failed(__FILE__,__LINE__,#x))
double sqrt(double);
double fabs(double);
#endif
