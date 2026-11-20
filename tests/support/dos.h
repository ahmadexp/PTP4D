#ifndef MOCK_DOS_H
#define MOCK_DOS_H
#define far
union REGS {
    struct {unsigned short ax,bx,cx,dx,si,di,cflag;} x;
    struct {unsigned char al,ah,bl,bh,cl,ch,dl,dh;} h;
};
void *mock_far(unsigned segment,unsigned offset);
#define MK_FP(s,o) mock_far((s),(o))
int int86(int n,union REGS *in,union REGS *out);
#endif
