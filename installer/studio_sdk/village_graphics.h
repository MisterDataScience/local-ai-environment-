#ifndef VILLAGE_GRAPHICS_H
#define VILLAGE_GRAPHICS_H
#include "village_machine.h"
/* Small reusable C helpers. Pixels, palettes and fonts remain project-owned data. */
static inline void vm_sprite(const uint8_t *pixels, const uint32_t *palette,
 int width, int height, int stride, int x, int y, int transparent, int scale) {
    if (!pixels || !palette || width<1 || height<1 || stride<width || scale<1 || scale>16) return;
    for (int row=0;row<height;row++) for (int col=0;col<width;col++) {
        unsigned index=pixels[row*stride+col];
        if ((int)index==transparent) continue;
        int px=x+col*scale,py=y+row*scale;
        if(px>=VM_WIDTH || py>=VM_HEIGHT || px+scale<=0 || py+scale<=0)continue;
        vm_rect(px,py,scale,scale,(int)palette[index]);
    }
}
/* Font: 96 printable ASCII glyphs, eight rows per glyph, high bit on the left. */
static inline void vm_text8(const uint8_t *font,const char *text,int x,int y,int colour) {
    if(!font || !text)return;
    int origin=x;
    for(int i=0;text[i] && i<4096;i++) {
        unsigned c=(unsigned char)text[i];
        if(c=='\n'){x=origin;y+=8;continue;}
        if(c<32 || c>127)c='?';
        for(int row=0;row<8;row++)for(int col=0;col<8;col++)
            if(font[(c-32)*8+row]&(128>>col))vm_pixel(x+col,y+row,colour);
        x+=8;
    }
}
/* Tile IDs index a tightly packed, row-major atlas. No hidden world-size limit. */
static inline void vm_tiles(const uint16_t *map,int columns,int rows,
 const uint8_t *atlas,int atlas_width,int atlas_height,int tile_size,
 const uint32_t *palette,int camera_x,int camera_y,int transparent) {
    if(!map || !atlas || !palette || columns<1 || rows<1 || tile_size<1 || atlas_width<tile_size || atlas_height<tile_size)return;
    int across=atlas_width/tile_size,down=atlas_height/tile_size;
    int first_x=camera_x>0?camera_x/tile_size:0,first_y=camera_y>0?camera_y/tile_size:0;
    for(int row=first_y;row<rows && row*tile_size-camera_y<VM_HEIGHT;row++)
      for(int col=first_x;col<columns && col*tile_size-camera_x<VM_WIDTH;col++) {
        unsigned tile=map[row*columns+col];if(tile>=(unsigned)(across*down))continue;
        const uint8_t *pixels=atlas+(tile/across)*tile_size*atlas_width+(tile%across)*tile_size;
        vm_sprite(pixels,palette,tile_size,tile_size,atlas_width,col*tile_size-camera_x,row*tile_size-camera_y,transparent,1);
      }
}
static inline int vm_overlap(int ax,int ay,int aw,int ah,int bx,int by,int bw,int bh) {
    return aw>0 && ah>0 && bw>0 && bh>0 && ax<bx+bw && bx<ax+aw && ay<by+bh && by<ay+ah;
}
#endif
