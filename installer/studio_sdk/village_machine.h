#ifndef VILLAGE_MACHINE_H
#define VILLAGE_MACHINE_H
#include <stdint.h>
#define VM_WIDTH 320
#define VM_HEIGHT 180
#define VM_UP 1
#define VM_DOWN 2
#define VM_LEFT 4
#define VM_RIGHT 8
#define VM_A 16
#define VM_B 32
#define VM_START 64
#define VM_SELECT 128
#define VM_IMPORT(name) __attribute__((import_module("vm"), import_name(name)))
VM_IMPORT("clear") void vm_clear(int colour);
VM_IMPORT("pixel") void vm_pixel(int x,int y,int colour);
VM_IMPORT("rect") void vm_rect(int x,int y,int width,int height,int colour);
VM_IMPORT("tone") void vm_tone(int channel,int frequency,int ticks,int volume);
VM_IMPORT("metric") void vm_metric(int key,int value);
VM_IMPORT("save") int vm_save(const void *data,int bytes);
VM_IMPORT("load") int vm_load(void *data,int capacity);
VM_IMPORT("asset_size") int vm_asset_size(int asset);
VM_IMPORT("asset_read") int vm_asset_read(int asset,int offset,void *destination,int bytes);
/* Export these. vm_draw must leave simulation memory unchanged. */
void vm_init(int seed);
void vm_update(int buttons);
void vm_draw(void);
#endif
