#!/usr/bin/env python3
"""Execute the actual patched MIPS callback with stock filter and mocked UI services.
Requires unicorn==2.1.4. Does not emulate the entire device or flash hardware.
"""
import json, math, pathlib, re, struct, sys
from unicorn import Uc, UcError, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
from build import segments, symbols, HOOK, HOOKS, FUNCTIONS, GLOBALS, ROOT, source_sha256
B=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'build')
manifest=json.loads((B/'manifest.json').read_text())
if manifest.get('source_sha256') != source_sha256():
    raise SystemExit(f'{B}/manifest.json does not match the current patch sources; rebuild into a fresh directory and pass it here')
O={m.group(1):int(m.group(2),0) for m in re.finditer(r'^#define\s+(\w+)\s+(0x[0-9A-Fa-f]+|\d+)\b',(ROOT/'patch/offsets.inc').read_text(),re.M)}
syms=symbols(B/'stock-demo')
VG_MOCKS=[n for n in syms if n.startswith(('vgcanvas_','vg_gradient_'))]

def _fp64_fix():
    """The stock binary is -mfp64 (FR=1); Unicorn's MIPS32 FPU only implements FR=0, so
    L-format conversions are rewritten to their W equivalents when an image is loaded. Every
    value the traversed canvas code converts fits 32 bits, so the results are identical."""
    data=(B/'demo').read_bytes(); fixes=[]
    for _,(t,o,v,_,f,m,flags,_) in segments(data):
        if t!=1 or not flags&1: continue
        for off in range(o,o+f,4):
            w=struct.unpack_from('<I',data,off)[0]
            if w>>26&0x3f==0x11 and w>>21&0x1f==0x15:
                fixes.append((v+off-o,(w&~(0x1f<<21))|(0x14<<21)))
    return fixes
FP64_FIX=_fp64_fix()
REGS=[UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3]
SAVED=[UC_MIPS_REG_S0,UC_MIPS_REG_S1,UC_MIPS_REG_S2,UC_MIPS_REG_S3,
       UC_MIPS_REG_S4,UC_MIPS_REG_S5,UC_MIPS_REG_S6,UC_MIPS_REG_S7,UC_MIPS_REG_FP]

def signed(x): return x if x<0x80000000 else x-0x100000000

class Machine:
    def __init__(self, patched=True):
        self.u=Uc(UC_ARCH_MIPS, UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
        data=(B/('demo' if patched else 'stock-demo')).read_bytes()
        for _,(t,o,v,_,f,m,flags,_) in segments(data):
            if t!=1: continue
            start=v&~4095; end=(v+m+4095)&~4095
            self.u.mem_map(start,end-start)
            self.u.mem_write(v,data[o:o+f])
            # Payload text is execute-only; its top page holds the scratch cell.
            if v==0xb00000: self.u.mem_protect(start,0xb0f000-start,5)
        for v,w in FP64_FIX: self.u.mem_write(v,struct.pack('<I',w))
        self.u.mem_map(0x1000000,0x200000)
        self.u.mem_map(0x70000000,0x10000)
        self.next=0x1001000; self.nodes={}; self.calls=[]; self.animating=0; self.pressed=0
        self.top=0; self.wm=0x1000000; self.event=0x1000100
        self.strokes=[]; self.rounded=[]; self.vg_calls=[]; self.fake_vg=0; self.global_alpha=0
        self.rounded_fail=False
        self.allocs={}
        self.rebind=None; self.on_click=None; self.glide=True
        self.canvas=0x1000200; self.lcd=0x1000300; self.now=1000
        self.word(self.canvas+O['CANVAS_LCD'],self.lcd)
        self.word(self.lcd+O['LCD_FILL_COLOR'],0x9abcdef0)
        self.word(self.lcd+O['LCD_STROKE_COLOR'],0x12345678)
        self.clip=(0,0,240,240)
        self.handlers={}
        for name in FUNCTIONS: self.handlers[syms[name]]=name
        if patched:
            for name in ('paint','dispatch'):
                self.handlers[int(manifest['patch_symbols']['stock_'+name+'_trampoline'],16)]='stock_'+name
        self.handlers[syms['reset_poweroptions_timer']]='reset_poweroptions_timer'
        self.handlers[syms['memcpy@GLIBC_2.0']]='memcpy'
        self.handlers[syms['memset@GLIBC_2.0']]='memset'
        self.handlers[syms['canvas_set_global_alpha']]='canvas_set_global_alpha'
        for n in ('sqrtf@GLIBC_2.0','sinf@GLIBC_2.0','acosf@GLIBC_2.0'):
            self.handlers[syms[n]]='float:'+n
        for n in VG_MOCKS: self.handlers[syms[n]]='vg:'+n
        self.u.hook_add(UC_HOOK_CODE,self.hook)
        for name in GLOBALS: self.byte(syms[name],0)
        self.byte(syms['g_backlight_status'],1)
    def probe_canvas(self, lcd_type=1):
        """Real stock canvas code runs; mock only the services it reaches."""
        for n in ('canvas_fill_rounded_rect','canvas_stroke_rounded_rect','canvas_set_fill_color'):
            del self.handlers[syms[n]]
        self.handlers[syms['lcd_get_vgcanvas']]='lcd_get_vgcanvas'
        for n in ('tk_calloc','tk_free'): self.handlers[syms[n]]='alloc:'+n
        for off,val in ((0x10,0),(0x14,0),(0x18,239),(0x1c,239)): self.word(self.canvas+off,val)
        self.word(self.lcd+0xd0,lcd_type)
        self.rounded_fail=False
        self.rect=self.alloc(16); self.color=self.alloc(4)
    def byte(self,a,v): self.u.mem_write(a,bytes([v]))
    def word(self,a,v): self.u.mem_write(a,struct.pack('<I',v&0xffffffff))
    def get(self,a): return struct.unpack('<I',self.u.mem_read(a,4))[0]
    def alloc(self,n=0x200): a=self.next; self.next+=n; return a
    def string(self,s):
        a=self.alloc((len(s)+4)&~3); self.u.mem_write(a,s.encode()+b'\0'); return a
    def text(self,a):
        if not a: return ''
        out=bytearray()
        while (c:=self.u.mem_read(a,1))!=b'\0': out+=c; a+=1
        return out.decode()
    def node(self,t='scroll_view',name='',children=(),visible=1,enable=1,**kw):
        a=self.alloc(); self.nodes[a]=dict(type=t,name=name,children=list(children),visible=visible,enable=enable,**kw)
        self.word(a+O['W_W'],240); self.word(a+O['W_H'],240); self.word(a+O['ROW_HEIGHT'],48)
        self.word(a+(O['VIEW_CONTENT_H'] if t=='scroll_view' else O['TABLE_ROWS']),960 if t=='scroll_view' else 100)
        self.byte(a+O['VIEW_VERTICAL'],1)
        return a
    def entry(self,parent,y=0,index=None,t='list_item'):
        """A leafless tap target: emitter with one EVT_CLICK item, widget_y offset y, height 48."""
        a=self.node(t)
        em=self.alloc(4); it=self.alloc(0x28)
        self.word(a+O['W_EMITTER'],em); self.word(em,it); self.word(it+O['EMIT_TYPE'],O['EVT_CLICK'])
        self.word(a+O['W_PARENT'],parent); self.word(a+O['W_Y'],y); self.word(a+O['W_H'],48)
        if index is not None: self.word(a+O['ROW_INDEX'],index)
        return a
    def selected(self,w): return self.nodes[w].get('_ringnav_index',-1)
    def paint(self,w): return self.call(address=HOOKS['widget_on_paint_border'][0],args=(w,self.canvas,0,0))
    def touch(self): return self.call(address=HOOKS['on_wm_tsdown_before_fun'][0])
    def click(self,w): return self.call(address=HOOKS['widget_dispatch'][0],args=(w,self.event,0,0),event_type=O['EVT_CLICK'])
    def hook(self,u,address,size,_):
        if address not in self.handlers: return
        name=self.handlers[address]
        if not name.startswith('stock_'):
            assert u.reg_read(UC_MIPS_REG_T9)==address, (name,'PIC call missing t9')
        a,b,c,d=[u.reg_read(r) for r in REGS]
        n=self.nodes.get(a,{})
        self.calls.append((name,a,b,c))
        if name=='memcpy': self.u.mem_write(a,bytes(self.u.mem_read(b,c))); ret=a
        elif name=='memset': self.u.mem_write(a,bytes([b&255])*c); ret=a
        elif name=='window_manager': ret=self.wm
        elif name=='window_manager_get_top_window': ret=self.top
        elif name=='window_manager_is_animating': ret=self.animating
        elif name=='window_manager_get_pointer_pressed': ret=self.pressed
        elif name=='widget_get_visible': ret=n.get('visible',0)
        elif name=='widget_get_type': ret=self.string(n.get('type',''))
        elif name=='widget_get_prop_str': ret=self.string(n.get(self.text(b),''))
        elif name in ('widget_get_prop_bool','widget_get_prop_int'): ret=n.get(self.text(b),c)
        elif name=='widget_count_children': ret=len(n['children'])
        elif name=='widget_get_child': ret=n['children'][b] if b<len(n['children']) else 0
        elif name=='widget_set_prop_int': n[self.text(b)]=signed(c); ret=0
        elif name=='pointer_event_init':
            self.word(a,b); self.word(a+0x10,c); ret=a
        elif name=='time_now_ms': ret=self.now
        elif name=='tk_strcmp': ret=0 if a and b and self.text(a)==self.text(b) else -1
        elif name=='stock_dispatch':
            if self.on_click: self.on_click(a,b)
            ret=0
        elif name=='table_client_stop_animator_scroll': self.word(a+O['TABLE_ANIMATOR'],0); ret=0
        elif name=='table_client_scroll_to':
            if self.glide:
                self.word(a+O['TABLE_TOP'],b)
                if self.rebind: self.rebind(a,b)
            else: self.word(a+O['TABLE_ANIMATOR'],0x1234)
            ret=0
        elif name=='canvas_get_clip_rect':
            for j,v in enumerate(self.clip): self.word(b+4*j,v)
            ret=0
        elif name=='canvas_set_clip_rect': self.clip=tuple(signed(self.get(b+4*j)) for j in range(4)); ret=0
        elif name=='canvas_set_fill_color': self.word(self.lcd+O['LCD_FILL_COLOR'],b); ret=0
        elif name=='canvas_set_stroke_color': self.word(self.lcd+O['LCD_STROKE_COLOR'],b); ret=0
        elif name=='canvas_set_global_alpha': self.global_alpha+=1; ret=0
        elif name in ('canvas_fill_rounded_rect','canvas_stroke_rounded_rect'):
            sp=u.reg_read(UC_MIPS_REG_SP)
            # The stock rounded calls set the matching LCD color on their CPU branch; model that
            # stricter side effect so a missing restore fails the state assertions below.
            kind='fill' if name=='canvas_fill_rounded_rect' else 'stroke'
            radius=self.get(sp+16); width=None if kind=='fill' else self.get(sp+20)
            self.rounded.append(dict(kind=kind,rect=tuple(signed(self.get(b+4*j)) for j in range(4)),
                bg=signed(c),color=self.get(d),radius=radius,width=width,clip=self.clip))
            if kind=='stroke' and self.rounded_fail:
                ret=2   # a backend that declines to draw, as the stock no-vgcanvas path does
            else:
                self.word(self.lcd+(O['LCD_FILL_COLOR'] if kind=='fill' else O['LCD_STROKE_COLOR']),self.get(d))
                ret=0
        elif name in ('canvas_stroke_rect','lcd_stroke_rect'):
            h=self.get(u.reg_read(UC_MIPS_REG_SP)+16)
            clip=self.clip if name=='canvas_stroke_rect' else (self.get(self.canvas+0x10),self.get(self.canvas+0x14),self.get(self.canvas+0x18)-self.get(self.canvas+0x10)+1,self.get(self.canvas+0x1c)-self.get(self.canvas+0x14)+1)
            self.strokes.append((signed(b),signed(c),signed(d),signed(h),clip,self.get(self.lcd+O['LCD_STROKE_COLOR']))); ret=0
        elif name=='scroll_view_scroll_delta_to':
            if self.glide:
                self.word(a+O['SCROLL_X'],self.get(a+O['SCROLL_X'])+b); self.word(a+O['SCROLL_Y'],self.get(a+O['SCROLL_Y'])+c)
            else: self.word(a+O['VIEW_ANIMATOR'],0x1234)
            ret=0
        elif name=='lcd_get_vgcanvas': ret=self.fake_vg
        elif name.startswith('vg:'):
            self.vg_calls.append((name[3:],signed(a),signed(b),signed(c),signed(d),
                                  u.reg_read(UC_MIPS_REG_F12),u.reg_read(UC_MIPS_REG_F14),
                                  self.get(u.reg_read(UC_MIPS_REG_SP)+16)))
            ret=1 if name[3:]=='vgcanvas_save' else 0
        elif name.startswith('float:'):
            x=struct.unpack('<f',struct.pack('<I',u.reg_read(UC_MIPS_REG_F12)))[0]
            fn={'sqrtf@GLIBC_2.0':math.sqrt,'sinf@GLIBC_2.0':math.sin,'acosf@GLIBC_2.0':math.acos}[name[6:]]
            ret=struct.unpack('<I',struct.pack('<f',fn(x)))[0]
            u.reg_write(UC_MIPS_REG_F0,ret)
        elif name in ('alloc:tk_calloc','alloc:tk_free'):
            if name=='alloc:tk_calloc':
                size=a*b; p=self.alloc(size+16); self.allocs[p]=size; ret=p
            else:
                self.allocs.pop(a,None); ret=0
        else: ret=0
        # Clobber caller-saved registers to catch accidental ABI assumptions.
        for r in [UC_MIPS_REG_V1,*REGS,UC_MIPS_REG_T0,UC_MIPS_REG_T1,UC_MIPS_REG_T2,
                  UC_MIPS_REG_T3,UC_MIPS_REG_T4,UC_MIPS_REG_T5,UC_MIPS_REG_T6,
                  UC_MIPS_REG_T7,UC_MIPS_REG_T8,UC_MIPS_REG_T9]:
            u.reg_write(r,0xdeadbeef)
        u.reg_write(UC_MIPS_REG_V0,ret&0xffffffff)
        u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
    def call(self,key=O['KEY_NEXT'],address=HOOK,args=None,event_type=0x114,gap=1000,stack=()):
        # Independent input steps occur after the stock key debounce timer expires.
        self.now+=gap
        self.byte(0xa37c89,0)
        self.calls=[]; self.strokes=[]; self.rounded=[]; self.vg_calls=[]
        self.word(self.event+O['EVENT_KEY'],key)
        self.word(self.event+O['EVENT_TYPE'],event_type)
        self.u.reg_write(UC_MIPS_REG_SP,0x7000f000)
        self.u.reg_write(UC_MIPS_REG_RA,0x1000000)
        self.u.reg_write(UC_MIPS_REG_T9,address)
        for i,v in enumerate(stack): self.word(0x7000f010+4*i,v)
        for r,v in zip(REGS,args or (self.wm,self.event,0,0)): self.u.reg_write(r,v&0xffffffff)
        for i,r in enumerate(SAVED): self.u.reg_write(r,0x12340000+i)
        self.u.emu_start(address,0x1000000,count=100000)
        assert self.u.reg_read(UC_MIPS_REG_PC)==0x1000000, 'Instruction limit reached'
        assert self.u.reg_read(UC_MIPS_REG_SP)==0x7000f000
        assert [self.u.reg_read(r) for r in SAVED]==[0x12340000+i for i in range(len(SAVED))]
        return signed(self.u.reg_read(UC_MIPS_REG_V0))
    def page(self,name='sysset_page',t='scroll_view'):
        child=self.node(t)
        self.top=self.node('window',name,[child])
        return child
    def page_list(self,n=10,height=96,extent=960,name='sysset_page'):
        """A page holding one scroll view of n 48px entries; returns (surface, entries)."""
        w=self.page(name); self.word(w+O['W_H'],height); self.word(w+O['VIEW_CONTENT_H'],extent)
        es=[self.entry(w,i*48) for i in range(n)]
        self.nodes[w]['children']=es
        return w,es
    def table_page(self,n=4,rows=20,height=96):
        """A table_client page of n recycled rows; returns (surface, row widgets, entries)."""
        w=self.page('allmusic_page','table_client')
        self.word(w+O['ROW_HEIGHT'],48); self.word(w+O['TABLE_ROWS'],rows); self.word(w+O['W_H'],height)
        rs=[self.node('table_row') for _ in range(n)]
        es=[self.entry(r) for r in rs]; self.nodes[w]['children']=rs
        for j,(r,e) in enumerate(zip(rs,es)):
            self.nodes[r]['children']=[e]; self.word(r+O['W_PARENT'],w)
            self.word(r+O['ROW_INDEX'],j); self.word(r+O['W_Y'],j*48)
        return w,rs,es
    def moved(self): return [x for x in self.calls if x[0] in ('scroll_view_scroll_delta_to','table_client_scroll_to','slide_menu_scroll_to_next','slide_menu_scroll_to_prev')]
    def dispatched(self): return [x for x in self.calls if x[0]=='stock_dispatch']

checks=0
def passed():
    global checks
    checks+=1

for t,off in [('scroll_view',O['SCROLL_Y']),('table_client',O['TABLE_TOP'])]:
    m=Machine(); w=m.page(t=t)
    for _ in range(20): assert m.call()==11
    assert m.get(w+off)==min(20*manifest['ring_step_pixels'],720 if t=='scroll_view' else 4560)
    assert m.call(O['KEY_PREV'])==11 and m.moved()
    for _ in range(120): m.call(O['KEY_PREV'])
    assert m.get(w+off)==0
    # Empty/short lists consume input without turning into volume changes.
    m.word(w+(O['VIEW_CONTENT_H'] if t=='scroll_view' else O['TABLE_ROWS']),0)
    assert m.call()==11 and m.get(w+off)==0
    passed()

for name in ['playing_page','volume_dialog','saverscreen_page','usbmode_page','unknown_page','equalizer_page']:
    m=Machine(); m.page(name); assert m.call()==0 and not m.moved(); passed()
for flag,value in [('g_backlight_status',0),('g_lockscreen_pageflag',1),('g_testmode_flag',1),
                   ('g_guideflag',1),('g_poweroff_state',2),('g_usblink_status',2),('bt__recv_pageflag',1)]:
    m=Machine(); m.page(); m.byte(syms[flag],value); assert m.call()==0 and not m.moved(); passed()
for field in ['animating','pressed']:
    m=Machine(); m.page(); setattr(m,field,1); assert m.call()==11 and not m.moved(); passed()

m=Machine(); w=m.page('home_page','slide_menu')
assert m.call()==11 and m.moved()[0][0]=='slide_menu_scroll_to_next'
assert m.call(O['KEY_PREV'])==11 and m.moved()[0][0]=='slide_menu_scroll_to_prev'; passed()
m=Machine(); hidden=m.node(visible=0); shown=m.node(); pages=m.node('pages',children=[hidden,shown],active=1)
m.top=m.node('window','artistinfo_page',[pages]); assert m.call()==11 and m.moved()[0][1]==shown; passed()
m.nodes[hidden]['visible']=1
assert m.call()==11 and m.moved()[0][1]==shown; passed()
m.top=m.node('window','sysset_page',[hidden,shown]); assert m.call()==11 and not m.moved(); passed()
# A horizontal scroll view is not a navigation pane and cannot make a page ambiguous.
m=Machine(); vert=m.node(); horiz=m.node(); m.word(horiz+O['VIEW_HORIZONTAL'],1)
m.top=m.node('window','sysset_page',[horiz,vert])
assert m.call()==11 and m.moved()[0][1]==vert; passed()
# Two navigable panes: only the pane that already holds the selection is used.
m=Machine(); a=m.node(); b=m.node(); m.word(a+O['W_H'],96); m.word(b+O['W_H'],96)
for s in (a,b):
    es=[m.entry(s,i*48) for i in range(4)]; m.nodes[s]['children']=es
m.top=m.node('window','album_page',[a,b])
m.nodes[a]['_ringnav_index']=0
assert m.call()==11 and m.call()==11
assert m.moved()[-1][1]==a
m.nodes[b]['_ringnav_index']=0
assert m.call()==11 and not m.moved(); passed()
for attribute in ['visible','enable']:
    m=Machine(); w=m.page(); m.nodes[w][attribute]=0; assert m.call()==11 and not m.moved(); passed()
# An in-flight scroll animation is retargeted by the animated glide, not torn down.
m=Machine(); w=m.page(); m.word(w+O['SCROLL_Y'],100)
assert m.call()==11 and m.moved()[0][0]=='scroll_view_scroll_delta_to' and m.moved()[0][3]==48
assert m.get(w+O['SCROLL_Y'])==148 and m.get(w+O['VIEW_ANIMATOR'])==0; passed()

# Painting establishes selection without a sacrificial button press or native focus.
m=Machine(); w,entries=m.page_list(5,extent=1000)
assert m.paint(w)==0 and m.selected(w)==0
# Default outline: translucent fill, one dark shade stroke, one white stroke, all clipped.
assert [r['kind'] for r in m.rounded]==['fill','stroke','stroke']
fill,shade,white=m.rounded
assert fill['rect']==(1,1,238,46) and fill['bg']==0 and fill['clip']==(0,0,240,96)
assert fill['color']==((O['FILL_ALPHA']<<24)|O['FILL_RGB']) and fill['radius']==O['RADIUS'] and fill['width'] is None
assert shade['rect']==(1,1,238,46) and shade['bg']==0
assert shade['color']==((O['SHADE_ALPHA']<<24)|O['FILL_RGB'])
assert shade['radius']==O['RADIUS'] and shade['width']==1 and shade['clip']==(0,0,240,96)
assert white['rect']==(2,2,236,44) and white['bg']==0 and white['color']==0xffffffff
assert white['radius']==O['RADIUS']-1 and white['width']==1
assert not m.strokes and m.global_alpha==0
assert m.clip==(0,0,240,240)
assert m.get(m.lcd+O['LCD_FILL_COLOR'])==0x9abcdef0 and m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x12345678
assert not any(m.get(e+O['W_FOCUS'])&0x80 for e in entries)
assert [c[0] for c in m.calls if c[0].startswith('canvas_')][-6:]==[
    'canvas_fill_rounded_rect','canvas_stroke_rounded_rect','canvas_stroke_rounded_rect',
    'canvas_set_fill_color','canvas_set_stroke_color','canvas_set_clip_rect']; passed()
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries[0]; passed()
assert m.call()==11 and m.selected(w)==1 and not m.moved()
assert m.call()==11 and m.selected(w)==2 and m.get(w+O['SCROLL_Y'])==48
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries[2]; passed()
# The separate Play/Pause key remains native even with an active selection.
assert m.call(O['KEY_PLAY'])==0 and not m.dispatched(); passed()
# Touching a different row selects it before the native callback runs; no extra click.
assert m.touch()==0
m.on_click=lambda a,b: (None if m.selected(w)==1 else (_ for _ in ()).throw(AssertionError('late selection')))
assert m.click(entries[1])==0 and len(m.dispatched())==1 and m.selected(w)==1
m.on_click=None
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries[1]; passed()
# Native touch focus may move anywhere without altering the logical selection.
m.word(entries[4]+O['W_FOCUS'],0x80)
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries[1]; passed()
# Swipe preserves selection during momentum; settle adopts the visible row nearest the centre.
m.touch(); m.word(w+O['SCROLL_Y'],110); m.word(w+O['VIEW_ANIMATOR'],0x1234)
m.paint(w); assert m.selected(w)==1
m.word(w+O['VIEW_ANIMATOR'],0); m.paint(w); assert m.selected(w)==3
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries[3]; passed()
# Wheel interrupts touch momentum, and centre while a finger is down is consumed without a click.
m.touch(); m.word(w+O['VIEW_ANIMATOR'],0x1234)
assert m.call(O['KEY_PREV'])==11 and m.get(w+O['VIEW_ANIMATOR'])==0 and m.selected(w)==2
m.pressed=1
assert m.call(O['KEY_CENTER'])==11 and not m.dispatched()
assert m.call()==11 and m.selected(w)==2
m.pressed=0; passed()
# With three rows in view the difference shows: the middle one wins, not the top edge.
m=Machine(); w,es=m.page_list(8,height=192,extent=1000)
m.paint(w); m.touch(); m.word(w+O['SCROLL_Y'],200); m.word(w+O['VIEW_ANIMATOR'],0x1234)
m.paint(w); assert m.selected(w)==0
m.word(w+O['VIEW_ANIMATOR'],0); m.paint(w); assert m.selected(w)==6; passed()
# Native click may destroy the current page. Nothing dereferences its target afterwards.
def destroy(a,b):
    m.nodes.clear(); m.top=0
m.on_click=destroy
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1; passed()

# Recycle a small row pool: selection belongs to the logical index, never the widget.
m=Machine(); w,rows,entries=m.table_page()
def rebind(a,offset):
    start=offset//48
    for j,r in enumerate(rows):
        m.word(r+O['ROW_INDEX'],start+j); m.word(r+O['W_Y'],(start+j)*48)
m.rebind=rebind; rebind(w,0)
m.paint(w); assert m.selected(w)==0
assert m.call()==11 and m.selected(w)==1
assert m.call()==11 and m.selected(w)==2 and m.get(w+O['TABLE_TOP'])==48
assert m.moved()[-1][0]=='table_client_scroll_to'
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries[1]; passed()
# A touch click in a rebound row immediately changes what centre opens.
m.touch(); m.click(entries[0]); assert m.selected(w)==1
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries[0]; passed()
# Swipe out of the old pool, then centre: settle/re-resolve before dispatch.
m.touch(); m.word(w+O['TABLE_TOP'],480); rebind(w,480); m.word(w+O['TABLE_ANIMATOR'],0x9876)
assert m.call(O['KEY_CENTER'])==11 and m.selected(w)==10 and m.dispatched()[0][1]==entries[0]
assert m.get(w+O['TABLE_ANIMATOR'])==0; passed()
# Returning to a surviving menu keeps a valid selection; shrinking data repairs it.
oldtop=m.top; m.page('playing_page'); assert m.call(O['KEY_CENTER'])==0
m.top=oldtop; m.paint(w); assert m.selected(w)==10
m.word(w+O['TABLE_ROWS'],1); m.word(w+O['TABLE_TOP'],0); rebind(w,0); m.paint(w)
assert m.selected(w)==0; passed()

# A recreated page recalls the last selected row and reveals it without a sacrificial press.
m=Machine(); w,es=m.page_list(10,extent=1000)
m.paint(w)
for _ in range(5): assert m.call()==11
assert m.selected(w)==5 and m.get(w+O['SCROLL_Y'])==192
w2,es2=m.page_list(10,extent=1000)
assert m.paint(w2)==0 and m.selected(w2)==5 and m.get(w2+O['SCROLL_Y'])==192
assert m.rounded[0]['rect']==(1,49,238,46) and m.rounded[0]['kind']=='fill'
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==es2[5]; passed()

# Memory is per audited context: visiting another page leaves it alone.
w3,es3=m.page_list(10,extent=1000,name='display_page')
assert m.paint(w3)==0 and m.selected(w3)==0
w4,es4=m.page_list(10,extent=1000)
assert m.paint(w4)==0 and m.selected(w4)==5; passed()

# A stale remembered row is ignored when the new list is shorter.
w5,es5=m.page_list(2,extent=300)
assert m.paint(w5)==0 and m.selected(w5)==0
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==es5[0]; passed()

# A settled swipe stores the row the user sees, not the pre-swipe selection.
m=Machine(); w,es=m.page_list(10,extent=1000)
m.paint(w); m.touch(); m.word(w+O['SCROLL_Y'],240); m.word(w+O['VIEW_ANIMATOR'],0x1234)
m.paint(w); assert m.selected(w)==0
m.word(w+O['VIEW_ANIMATOR'],0); m.paint(w); assert m.selected(w)==5
w2,es2=m.page_list(10,extent=1000)
assert m.paint(w2)==0 and m.selected(w2)==5 and m.get(w2+O['SCROLL_Y'])==192; passed()

# Position memory follows row text across a recreation, not just the index.
m=Machine(); w,es=m.page_list(6,extent=1000)
for i,e in enumerate(es): m.nodes[e]['text']='track %d'%i
m.paint(w)
for _ in range(4): assert m.call()==11
assert m.selected(w)==4
w2,es2=m.page_list(6,extent=1000)
order=[4,0,1,2,3,5]
for i,e in enumerate(es2): m.nodes[e]['text']='track %d'%order[i]
assert m.paint(w2)==0 and m.selected(w2)==0
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==es2[0]; passed()
# Rows without text fall back to the remembered index.
m=Machine(); w,es=m.page_list(6,extent=1000)
m.paint(w)
for _ in range(3): assert m.call()==11
assert m.selected(w)==3
w2,es2=m.page_list(6,extent=1000)
assert m.paint(w2)==0 and m.selected(w2)==3; passed()

# Duplicate row text restores the occurrence the user left, not the first duplicate.
m=Machine(); w,es=m.page_list(6,extent=1000)
for e in es: m.nodes[e]['text']='Intro'
m.paint(w)
for _ in range(4): assert m.call()==11
assert m.selected(w)==4
w2,es2=m.page_list(6,extent=1000)
for e in es2: m.nodes[e]['text']='Intro'
assert m.paint(w2)==0 and m.selected(w2)==4; passed()
# After a re-sort, equal-text rows resolve to the occurrence nearest the old position.
m=Machine(); w,es=m.page_list(6,extent=1000)
m.nodes[es[4]]['text']='dup'
m.paint(w)
for _ in range(4): assert m.call()==11
assert m.selected(w)==4
w2,es2=m.page_list(6,extent=1000)
m.nodes[es2[1]]['text']='dup'; m.nodes[es2[5]]['text']='dup'
assert m.paint(w2)==0 and m.selected(w2)==5; passed()
# Equal distance keeps the earlier duplicate.
m=Machine(); w,es=m.page_list(6,extent=1000)
m.nodes[es[3]]['text']='dup'
m.paint(w)
for _ in range(3): assert m.call()==11
assert m.selected(w)==3
w2,es2=m.page_list(6,extent=1000)
m.nodes[es2[2]]['text']='dup'; m.nodes[es2[4]]['text']='dup'
assert m.paint(w2)==0 and m.selected(w2)==2; passed()
# Two rows share a title; the second text decides before proximity does.
m=Machine(); w,es=m.page_list(4,extent=1000)
for e in es: m.nodes[e]['text']='Intro'
m.nodes[es[0]]['children']=[m.node('label',text='Artist A')]
m.nodes[es[1]]['children']=[m.node('label',text='Artist B')]
m.paint(w)
assert m.call()==11 and m.selected(w)==1
w2,es2=m.page_list(4,extent=1000)
for e in es2: m.nodes[e]['text']='Intro'
m.nodes[es2[2]]['children']=[m.node('label',text='Artist A')]
m.nodes[es2[3]]['children']=[m.node('label',text='Artist B')]
assert m.paint(w2)==0 and m.selected(w2)==3; passed()
# A subtitle missing from the recreated rows never blocks the primary match.
m=Machine(); w,es=m.page_list(4,extent=1000)
for e in es: m.nodes[e]['text']='Intro'
m.nodes[es[1]]['children']=[m.node('label',text='Artist B')]
m.paint(w)
assert m.call()==11 and m.selected(w)==1
w2,es2=m.page_list(4,extent=1000)
m.nodes[es2[0]]['text']='Intro'; m.nodes[es2[3]]['text']='Intro'
assert m.paint(w2)==0 and m.selected(w2)==0; passed()

# An interrupted recall glide keeps the remembered row instead of adopting a visible one.
m=Machine(); w,es=m.page_list(10,extent=1000)
m.paint(w)
for _ in range(5): assert m.call()==11
w2,es2=m.page_list(10,extent=1000)
m.glide=False
assert m.touch()==0
m.paint(w2); assert m.selected(w2)==5
w3,es3=m.page_list(10,extent=1000)
assert m.paint(w3)==0 and m.selected(w3)==5; passed()
# A wheel detent right after recreation computes its glide from the live offset.
m=Machine(); w,es=m.page_list(10,extent=1000)
m.paint(w)
for _ in range(5): assert m.call()==11
w2,es2=m.page_list(10,extent=1000)
m.glide=False
assert m.call()==11 and m.selected(w2)==6
assert m.moved()[-1][0]=='scroll_view_scroll_delta_to' and m.moved()[-1][3]==240; passed()

# A live list whose row count changes resets the selection without re-reading the table.
m=Machine(); w,es=m.page_list(10,extent=1000)
m.paint(w)
for _ in range(5): assert m.call()==11
assert m.selected(w)==5
m.nodes[w]['children']=es[:6]; m.word(w+O['VIEW_CONTENT_H'],6*48); m.word(w+O['SCROLL_Y'],0)
m.paint(w); assert m.selected(w)==0; passed()

# Virtual music tables recall a logical row and scroll to it on recreation.
m=Machine(); w,_,entries=m.table_page()
m.paint(w)
for _ in range(2): assert m.call()==11
assert m.selected(w)==2 and m.get(w+O['TABLE_TOP'])==48
m.rebind=None
w2,_,entries2=m.table_page()
m.paint(w2); assert m.selected(w2)==2 and m.get(w2+O['TABLE_TOP'])==48
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries2[2]; passed()

# Home keeps its native carousel presentation and value (including touch changes).
m=Machine(); w=m.page('home_page','slide_menu'); m.word(w+O['SLIDE_INDEX'],1)
child=[m.entry(w),m.entry(w)]; m.nodes[w]['children']=child
assert m.paint(w)==0 and not m.strokes and not m.rounded
assert any(c[0]=='stock_paint' for c in m.calls)
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==child[1]
m.word(w+O['SLIDE_INDEX'],0)
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==child[0]; passed()
# Long-press/boot release must reach stock cleanup, never activate a menu item.
for addr in [syms['g_power_longkey'],syms['g_ingore_bootkey_flag'],O['BOOT_KEY_GUARD']]:
    m.byte(addr,1); assert m.call(O['KEY_CENTER'])==0 and not m.dispatched(); m.byte(addr,0); passed()
# A quick second centre release reaches stock, whose short press toggles the screen.
m=Machine(); w,es=m.page_list(3)
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1
assert m.call(O['KEY_CENTER'],gap=100)==0 and not m.dispatched()
assert m.call(O['KEY_CENTER'],gap=100)==11 and len(m.dispatched())==1; passed()
# A wheel detent ends the double-click window: the next press selects instead.
m=Machine(); w,es=m.page_list(3)
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1
m.call(gap=50)
assert m.call(O['KEY_CENTER'],gap=50)==11 and len(m.dispatched())==1; passed()
# An empty menu consumes both presses; the window only arms after a real click.
m=Machine(); w=m.page()
assert m.call(O['KEY_CENTER'])==11 and not m.dispatched()
assert m.call(O['KEY_CENTER'],gap=100)==11 and not m.dispatched(); passed()
# A touch between the releases cancels the pair: the second press selects again.
m=Machine(); w,es=m.page_list(3)
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1
m.call(address=HOOKS['on_wm_tsdown_before_fun'][0], gap=100)
assert m.call(O['KEY_CENTER'],gap=100)==11 and m.dispatched()[0][1]==es[0]; passed()
# A different top window cancels the pair too: no screen toggle after navigation.
m=Machine(); w,es=m.page_list(3)
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1
w2,es2=m.page_list(3,name='display_page')
assert m.call(O['KEY_CENTER'],gap=100)==11 and m.dispatched()[0][1]==es2[0]; passed()
# Fast same-direction detents accelerate; a slow detent or a reversal starts over.
m=Machine(); w,es=m.page_list(40,extent=40*48)
m.paint(w)
assert m.call(O['KEY_NEXT'])==11 and m.selected(w)==1
for want in (2,4,6,8,12,16,20,28,36,39,39):
    assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==want
assert m.call(O['KEY_PREV'],gap=50)==11 and m.selected(w)==38
assert m.call(O['KEY_NEXT'],gap=1000)==11 and m.selected(w)==39; passed()
# Fast detents accelerate the pixel-scroll fallback the same way.
m=Machine(); w=m.page(t='table_client')
assert m.call(gap=50)==11 and m.get(w+O['TABLE_TOP'])==48
assert m.call(gap=50)==11 and m.get(w+O['TABLE_TOP'])==96
assert m.call(gap=50)==11 and m.get(w+O['TABLE_TOP'])==192
assert m.call(gap=1000)==11 and m.get(w+O['TABLE_TOP'])==240; passed()
# A click on a clickable child selects its collected ancestor, not a stale row.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
row1=m.entry(w,0); row2=m.entry(w,96); deep=m.entry(row1,0)
m.nodes[row1]['children']=[deep]; m.nodes[w]['children']=[row1,row2]
m.paint(w); assert m.selected(w)==0
assert m.call(O['KEY_NEXT'])==11 and m.selected(w)==1
m.click(deep); assert m.selected(w)==0
m.click(m.node('button')); assert m.selected(w)==0; passed()
# Real canvas ABI, translation and clip code execute; only the LCD rectangle sink is mocked.
# A 20px row keeps the square fallback (radius 9 needs more height), so the stock square code
# runs with the real clip intersection and color restore.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
e=m.entry(w,0); m.word(e+O['W_H'],20); m.nodes[w]['children']=[e]
for name in ('canvas_get_clip_rect','canvas_set_clip_rect','canvas_set_stroke_color','canvas_stroke_rect'):
    del m.handlers[syms[name]]
m.handlers[syms['lcd_stroke_rect']]='lcd_stroke_rect'
m.word(m.lcd+0x3c,1); m.word(m.lcd+0xb0,240); m.word(m.lcd+0xb4,240)
m.word(m.canvas+O['CANVAS_X'],7); m.word(m.canvas+O['CANVAS_Y'],20)
for off,val in [(0x10,10),(0x14,30),(0x18,229),(0x1c,199)]: m.word(m.canvas+off,val)
m.paint(w)
assert not m.rounded and [s[:4] for s in m.strokes]==[(8,21,238,18),(9,22,236,16)]
assert m.strokes[0][4:]==((10,30,220,86),((O['SHADE_ALPHA']<<24)|O['FILL_RGB']))
assert m.strokes[1][4:]==((10,30,220,86),0xffffffff)
assert [m.get(m.canvas+off) for off in (0x10,0x14,0x18,0x1c)]==[10,30,229,199]
assert m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x12345678; passed()
# Centre and rapid wheel reversals retain the selected item during an unfinished wheel glide.
m=Machine(); w,es=m.page_list(6)
m.paint(w); m.glide=False
m.call(); m.call(); assert m.selected(w)==2 and m.get(w+O['SCROLL_Y'])==0
m.paint(w); assert m.selected(w)==2
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==es[2]
m.call(); assert m.selected(w)==3
m.call(O['KEY_PREV']); assert m.selected(w)==2
m.call(O['KEY_PREV']); assert m.selected(w)==1 and m.get(w+O['VIEW_ANIMATOR'])==0; passed()
# Empty menus never activate or turn off the screen; touch doesn't swallow its first event.
m=Machine(); w=m.page(); assert m.call(O['KEY_CENTER'])==11 and not m.dispatched()
assert m.touch()==0 and not m.dispatched(); passed()
# Clip an oversized target to its surface without losing its selection.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
e=m.entry(w); m.word(e+O['W_H'],140); m.nodes[w]['children']=[e]
m.paint(w)
assert m.selected(w)==0 and [r['kind'] for r in m.rounded]==['fill','stroke','stroke']
assert m.rounded[0]['rect']==(1,1,238,138) and all(r['clip']==(0,0,240,96) for r in m.rounded); passed()

# Small rows keep the square shade-plus-white outline; the rounded path starts only when both
# outer dimensions exceed 2*RADIUS. Tiny rows are skipped outright, never with negative sizes.
for ww,hh in [(240,20),(20,48),(6,6),(21,21)]:
    m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
    e=m.entry(w,0); m.word(e+O['W_W'],ww); m.word(e+O['W_H'],hh); m.nodes[w]['children']=[e]
    assert m.paint(w)==0
    if ww>2*O['RADIUS']+2 and hh>2*O['RADIUS']+2:
        assert [r['kind'] for r in m.rounded]==['fill','stroke','stroke'] and not m.strokes,(ww,hh,m.rounded,m.strokes)
    else:
        assert not m.rounded and [s[:4] for s in m.strokes]==[(1,1,ww-2,hh-2),(2,2,ww-4,hh-4)]
        assert [s[5] for s in m.strokes]==[((O['SHADE_ALPHA']<<24)|O['FILL_RGB']),0xffffffff]
    assert m.global_alpha==0 and m.clip==(0,0,240,240)
    assert m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x12345678; passed()
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
e=m.entry(w,0); m.word(e+O['W_W'],4); m.word(e+O['W_H'],4); m.nodes[w]['children']=[e]
assert m.paint(w)==0 and not m.rounded and not m.strokes and m.clip==(0,0,240,240); passed()
# A page with no entries paints nothing and leaves every saved property alone.
m=Machine(); w=m.page()
assert m.paint(w)==0 and m.selected(w)==-1
assert not m.rounded and not m.strokes and m.global_alpha==0 and m.clip==(0,0,240,240)
assert m.get(m.lcd+O['LCD_FILL_COLOR'])==0x9abcdef0 and m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x12345678; passed()

# Every saved value is unusual: the rounded path restores fill, stroke and clip exactly and
# never touches the canvas or LCD global-alpha bytes.
m=Machine(); w,es=m.page_list(3,extent=1000)
m.word(m.lcd+O['LCD_FILL_COLOR'],0x00000001); m.word(m.lcd+O['LCD_STROKE_COLOR'],0x80ffffff)
m.byte(m.canvas+0x0e,0x7f); m.byte(m.lcd+0xe4,0x11)
m.paint(w)
assert m.get(m.lcd+O['LCD_FILL_COLOR'])==0x00000001 and m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x80ffffff
assert m.u.mem_read(m.canvas+0x0e,1)[0]==0x7f and m.u.mem_read(m.lcd+0xe4,1)[0]==0x11
assert m.global_alpha==0 and m.clip==(0,0,240,240); passed()

# An inactive pane is never painted, so the outline cannot appear on two panes at once.
m=Machine(); a=m.node(); b=m.node()
for s in (a,b):
    es=[m.entry(s,i*48) for i in range(4)]; m.nodes[s]['children']=es
m.word(a+O['W_H'],96); m.word(b+O['W_H'],96)
m.top=m.node('window','album_page',[a,b]); m.nodes[a]['_ringnav_index']=0
m.paint(b); assert not m.rounded and not m.strokes
m.paint(a); assert [r['kind'] for r in m.rounded]==['fill','stroke','stroke']; passed()

# A canvas backend that declines the rounded stroke keeps the outline via the square fallback.
m=Machine(); w,es=m.page_list(3,extent=1000); m.rounded_fail=True
m.paint(w)
assert [r['kind'] for r in m.rounded]==['fill','stroke'] and [s[:4] for s in m.strokes]==[(1,1,238,46),(2,2,236,44)]
assert m.rounded[1]['color']==((O['SHADE_ALPHA']<<24)|O['FILL_RGB'])
assert [s[5] for s in m.strokes]==[((O['SHADE_ALPHA']<<24)|O['FILL_RGB']),0xffffffff]
assert m.get(m.lcd+O['LCD_FILL_COLOR'])==0x9abcdef0 and m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x12345678
assert m.global_alpha==0 and m.clip==(0,0,240,240); passed()

# The real stock rounded wrappers run with canvas services mocked. This firmware declines with
# RET_FAIL when the canvas has no vgcanvas, and changes no fill/stroke color or alpha byte.
m=Machine(); m.probe_canvas(); m.fake_vg=0
for off,val in enumerate((1,1,238,46)): m.word(m.rect+4*off,val)
m.word(m.color,((O['FILL_ALPHA']<<24)|O['FILL_RGB']))
assert m.call(address=syms['canvas_fill_rounded_rect'],args=(m.canvas,m.rect,0,m.color),stack=(O['RADIUS'],))==2
assert m.call(address=syms['canvas_stroke_rounded_rect'],args=(m.canvas,m.rect,0,m.color),stack=(O['RADIUS'],1))==2
assert m.get(m.lcd+O['LCD_FILL_COLOR'])==0x9abcdef0 and m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x12345678
assert m.global_alpha==0 and not m.vg_calls; passed()

# With a vgcanvas present the same wrappers take the AGGE-facing path the Q2 firmware links:
# the color pointer and the radius/border-width stack slots reach the backend, canvas colors and
# the canvas alpha byte stay put. (The fill call then enters stock FP64 dither math that Unicorn's
# MIPS32 FR=0 FPU cannot execute; its vgcanvas calls up to that point are still asserted.)
m=Machine(); m.probe_canvas(); m.fake_vg=0x1000400
for off,val in enumerate((10,10,100,40)): m.word(m.rect+4*off,val)
m.word(m.color,0xffffffff)
assert m.call(address=syms['canvas_stroke_rounded_rect'],args=(m.canvas,m.rect,0,m.color),stack=(O['RADIUS'],2))==0
names=[c[0] for c in m.vg_calls]
assert 'vgcanvas_set_stroke_color' in names and 'vgcanvas_set_line_width' in names
assert [c[2]&0xffffffff for c in m.vg_calls if c[0]=='vgcanvas_set_stroke_color']==[0xffffffff]
assert [struct.unpack('<f',struct.pack('<I',c[2]&0xffffffff))[0] for c in m.vg_calls if c[0]=='vgcanvas_set_line_width']==[2.0]
assert m.get(m.lcd+O['LCD_FILL_COLOR'])==0x9abcdef0 and m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x12345678
assert m.global_alpha==0 and m.u.mem_read(m.canvas+0x0e,1)[0]==0; passed()
m=Machine(); m.probe_canvas(); m.fake_vg=0x1000400
m.word(m.color,((O['FILL_ALPHA']<<24)|O['FILL_RGB']))
for off,val in enumerate((10,10,100,40)): m.word(m.rect+4*off,val)
try: m.call(address=syms['canvas_fill_rounded_rect'],args=(m.canvas,m.rect,0,m.color),stack=(O['RADIUS'],))
except UcError: pass
assert [c[2] for c in m.vg_calls if c[0]=='vgcanvas_set_fill_color']==[((O['FILL_ALPHA']<<24)|O['FILL_RGB'])]
assert m.get(m.lcd+O['LCD_FILL_COLOR'])==0x9abcdef0 and m.global_alpha==0
assert not m.allocs; passed()

# CPU-LCD branch: the stock fill has a real rasterizer that Unicorn can run end to end. With a
# non-color LCD type it fills the rounded rect through LCD sinks, frees every allocation, and
# declines radius <= 2 exactly as the stock code does.
m=Machine(); m.probe_canvas(lcd_type=0)
for n in ('lcd_fill_rect','lcd_draw_hline','lcd_draw_vline'): m.handlers[syms[n]]='sink:'+n
for off,val in enumerate((10,10,100,40)): m.word(m.rect+4*off,val)
m.word(m.color,((O['FILL_ALPHA']<<24)|O['FILL_RGB']))
assert m.call(address=syms['canvas_fill_rounded_rect'],args=(m.canvas,m.rect,0,m.color),stack=(O['RADIUS'],))==0
ops=[c for c in m.calls if c[0].startswith('sink:')]
assert ops and all(10<=signed(c[2])<=109 and 10<=signed(c[3])<=49 for c in ops)
assert not m.allocs
assert m.call(address=syms['canvas_fill_rounded_rect'],args=(m.canvas,m.rect,0,m.color),stack=(2,))==2
assert not [c for c in m.calls if c[0].startswith('sink:')]; passed()
# The actual stock filter runs first, including each screen-off lock mode.
for backlight in [0,1]:
    for mode in range(4):
        for key in [170,O['KEY_PLAY'],O['KEY_PREV'],O['KEY_NEXT'],O['KEY_CENTER'],222,223,42]:
            results=[]
            for patched in [False,True]:
                m=Machine(patched); m.page('playing_page')
                m.byte(syms['g_backlight_status'],backlight)
                m.byte(syms['g_keylock_flag'],1); m.byte(syms['g_keylock_mode'],mode)
                results.append(m.call(key))
            assert results[0]==results[1],(backlight,mode,key,results)
            passed()
# Non-ring keys on supported pages must pass through unchanged.
for key in [0,13,170,O['KEY_PLAY'],222,223,0xffffffff]:
    m=Machine(); m.page(); assert m.call(key)==0 and not m.moved(); passed()
# Execute original get_direction for wraparound, thresholds, and half-turn ambiguity.
for current,previous,threshold,want in [(5,195,5,-1),(195,5,5,1),(20,20,10,0),
    (30,20,10,0),(31,20,10,-1),(9,20,10,1),(120,20,10,0),(20,120,10,0)]:
    m=Machine(); assert m.call(address=syms['get_direction'],args=(current,previous,threshold,0))==want; passed()
print(f'{checks} MIPS execution scenarios passed; toolkit services mocked, stock lock filter executed.')
