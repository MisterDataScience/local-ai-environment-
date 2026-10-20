#include "village_machine.h"
static int x,y,ticks;
void vm_init(int seed) { x=16+(seed&31); y=80; ticks=0; }
void vm_update(int buttons) {
    if(buttons&VM_LEFT) x--;
    if(buttons&VM_RIGHT) x++;
    if(buttons&VM_UP) y--;
    if(buttons&VM_DOWN) y++;
    if(x<0)x=0; if(x>304)x=304;
    if(y<0)y=0; if(y>164)y=164;
    if(buttons&VM_A)vm_tone(0,440,6,15);
    ticks++; vm_metric(0,x); vm_metric(1,y); vm_metric(2,ticks);
}
void vm_draw(void) {
    vm_clear(0x18202b);
    vm_rect(0,164,320,16,0x284c40);
    vm_rect(x,y,16,16,0xffcb72);
    vm_rect(x+3,y+4,3,3,0x18202b);
    vm_rect(x+10,y+4,3,3,0x18202b);
}
