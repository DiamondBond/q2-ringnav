#!/usr/bin/env python3
"""Execute the actual patched MIPS callback with stock filter and mocked UI services.
Requires unicorn==2.1.4. Does not emulate the entire device or flash hardware.
"""
import json, pathlib, re, struct, sys
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
from build import segments, symbols, HOOK, HOOKS, FUNCTIONS, GLOBALS, ROOT, source_sha256
B=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'build')
manifest=json.loads((B/'manifest.json').read_text())
if manifest.get('source_sha256') != source_sha256():
    raise SystemExit(f'{B}/manifest.json does not match the current patch sources; rebuild into a fresh directory and pass it here')
O={m.group(1):int(m.group(2),0) for m in re.finditer(r'^#define\s+(\w+)\s+(0x[0-9A-Fa-f]+|\d+)\b',(ROOT/'patch/offsets.inc').read_text(),re.M)}
syms=symbols(B/'stock-demo')
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
        self.u.mem_map(0x1000000,0x200000)
        self.u.mem_map(0x70000000,0x10000)
        self.next=0x1001000; self.nodes={}; self.calls=[]; self.animating=0; self.pressed=0
        self.top=0; self.wm=0x1000000; self.event=0x1000100
        self.strokes=[]; self.rebind=None; self.on_click=None; self.glide=True
        self.canvas=0x1000200; self.lcd=0x1000300; self.now=1000
        self.word(self.canvas+O['CANVAS_LCD'],self.lcd)
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
        self.u.hook_add(UC_HOOK_CODE,self.hook)
        for name in GLOBALS: self.byte(syms[name],0)
        self.byte(syms['g_backlight_status'],1)
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
        elif name=='canvas_set_stroke_color': self.word(self.lcd+O['LCD_STROKE_COLOR'],b); ret=0
        elif name in ('canvas_stroke_rect','lcd_stroke_rect'):
            h=self.get(u.reg_read(UC_MIPS_REG_SP)+16)
            clip=self.clip if name=='canvas_stroke_rect' else (self.get(self.canvas+0x10),self.get(self.canvas+0x14),self.get(self.canvas+0x18)-self.get(self.canvas+0x10)+1,self.get(self.canvas+0x1c)-self.get(self.canvas+0x14)+1)
            self.strokes.append((signed(b),signed(c),signed(d),signed(h),clip,self.get(self.lcd+O['LCD_STROKE_COLOR']))); ret=0
        elif name=='scroll_view_scroll_delta_to':
            if self.glide:
                self.word(a+O['SCROLL_X'],self.get(a+O['SCROLL_X'])+b); self.word(a+O['SCROLL_Y'],self.get(a+O['SCROLL_Y'])+c)
            else: self.word(a+O['VIEW_ANIMATOR'],0x1234)
            ret=0
        else: ret=0
        # Clobber caller-saved registers to catch accidental ABI assumptions.
        for r in [UC_MIPS_REG_V1,*REGS,UC_MIPS_REG_T0,UC_MIPS_REG_T1,UC_MIPS_REG_T2,
                  UC_MIPS_REG_T3,UC_MIPS_REG_T4,UC_MIPS_REG_T5,UC_MIPS_REG_T6,
                  UC_MIPS_REG_T7,UC_MIPS_REG_T8,UC_MIPS_REG_T9]:
            u.reg_write(r,0xdeadbeef)
        u.reg_write(UC_MIPS_REG_V0,ret&0xffffffff)
        u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
    def call(self,key=O['KEY_NEXT'],address=HOOK,args=None,event_type=0x114,gap=1000):
        # Independent input steps occur after the stock key debounce timer expires.
        self.now+=gap
        self.byte(0xa37c89,0)
        self.calls=[]; self.word(self.event+O['EVENT_KEY'],key)
        self.word(self.event+O['EVENT_TYPE'],event_type)
        self.u.reg_write(UC_MIPS_REG_SP,0x7000f000)
        self.u.reg_write(UC_MIPS_REG_RA,0x1000000)
        self.u.reg_write(UC_MIPS_REG_T9,address)
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
    def moved(self): return [x for x in self.calls if x[0] in ('scroll_view_scroll_delta_to','table_client_scroll_to','slide_menu_scroll_to_next','slide_menu_scroll_to_prev')]
    def dispatched(self): return [x for x in self.calls if x[0]=='stock_dispatch']

checks=0
def passed():
    global checks
    checks+=1

for t,off in [('scroll_view',0x84),('table_client',0x80)]:
    m=Machine(); w=m.page(t=t)
    for _ in range(20): assert m.call()==11
    assert m.get(w+off)==min(20*manifest['ring_step_pixels'],720 if t=='scroll_view' else 4560)
    assert m.call(O['KEY_PREV'])==11 and m.moved()
    for _ in range(120): m.call(O['KEY_PREV'])
    assert m.get(w+off)==0
    # Empty/short lists consume input without turning into volume changes.
    m.word(w+0x7c,0); assert m.call()==11 and m.get(w+off)==0
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
m=Machine(); w=m.page(); m.word(w+O['W_H'],96); m.word(w+0x7c,1000)
entries=[m.entry(w,i*48) for i in range(5)]; m.nodes[w]['children']=entries
assert m.paint(w)==0 and m.selected(w)==0
assert m.strokes[0][:4]==(1,1,238,46) and m.strokes[0][5]==0xffffffff
assert m.clip==(0,0,240,240) and m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x12345678
assert not any(m.get(e+O['W_FOCUS'])&0x80 for e in entries); passed()
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
m=Machine(); w=m.page(); m.word(w+O['W_H'],192); m.word(w+0x7c,1000)
es=[m.entry(w,i*48) for i in range(8)]; m.nodes[w]['children']=es
m.paint(w); m.touch(); m.word(w+O['SCROLL_Y'],200); m.word(w+O['VIEW_ANIMATOR'],0x1234)
m.paint(w); assert m.selected(w)==0
m.word(w+O['VIEW_ANIMATOR'],0); m.paint(w); assert m.selected(w)==6; passed()
# Native click may destroy the current page. Nothing dereferences its target afterwards.
def destroy(a,b):
    m.nodes.clear(); m.top=0
m.on_click=destroy
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1; passed()

# Recycle a small row pool: selection belongs to the logical index, never the widget.
m=Machine(); w=m.page('allmusic_page','table_client')
m.word(w+0x78,48); m.word(w+0x7c,20); m.word(w+O['W_H'],96)
rows=[m.node('table_row') for _ in range(4)]
entries=[m.entry(r) for r in rows]; m.nodes[w]['children']=rows
for r,e in zip(rows,entries): m.nodes[r]['children']=[e]; m.word(r+O['W_PARENT'],w)
def rebind(a,offset):
    start=offset//48
    for j,r in enumerate(rows):
        m.word(r+0x78,start+j); m.word(r+4,(start+j)*48)
m.rebind=rebind; rebind(w,0)
m.paint(w); assert m.selected(w)==0
assert m.call()==11 and m.selected(w)==1
assert m.call()==11 and m.selected(w)==2 and m.get(w+0x80)==48
assert m.moved()[-1][0]=='table_client_scroll_to'
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries[1]; passed()
# A touch click in a rebound row immediately changes what centre opens.
m.touch(); m.click(entries[0]); assert m.selected(w)==1
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries[0]; passed()
# Swipe out of the old pool, then centre: settle/re-resolve before dispatch.
m.touch(); m.word(w+0x80,480); rebind(w,480); m.word(w+O['TABLE_ANIMATOR'],0x9876)
assert m.call(O['KEY_CENTER'])==11 and m.selected(w)==10 and m.dispatched()[0][1]==entries[0]
assert m.get(w+O['TABLE_ANIMATOR'])==0; passed()
# Returning to a surviving menu keeps a valid selection; shrinking data repairs it.
oldtop=m.top; m.page('playing_page'); assert m.call(O['KEY_CENTER'])==0
m.top=oldtop; m.paint(w); assert m.selected(w)==10
m.word(w+0x7c,1); m.word(w+0x80,0); rebind(w,0); m.paint(w)
assert m.selected(w)==0; passed()

# A recreated page recalls the last selected row and reveals it without a sacrificial press.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96); m.word(w+0x7c,1000)
es=[m.entry(w,i*48) for i in range(10)]; m.nodes[w]['children']=es
m.paint(w)
for _ in range(5): assert m.call()==11
assert m.selected(w)==5 and m.get(w+O['SCROLL_Y'])==192
w2=m.page(); m.word(w2+O['W_H'],96); m.word(w2+0x7c,1000)
es2=[m.entry(w2,i*48) for i in range(10)]; m.nodes[w2]['children']=es2
assert m.paint(w2)==0 and m.selected(w2)==5 and m.get(w2+O['SCROLL_Y'])==192
assert m.strokes[-2][:4]==(1,49,238,46)
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==es2[5]; passed()

# Memory is per audited context: visiting another page leaves it alone.
w3=m.page('display_page'); m.word(w3+O['W_H'],96); m.word(w3+0x7c,1000)
es3=[m.entry(w3,i*48) for i in range(10)]; m.nodes[w3]['children']=es3
assert m.paint(w3)==0 and m.selected(w3)==0
w4=m.page(); m.word(w4+O['W_H'],96); m.word(w4+0x7c,1000)
es4=[m.entry(w4,i*48) for i in range(10)]; m.nodes[w4]['children']=es4
assert m.paint(w4)==0 and m.selected(w4)==5; passed()

# A stale remembered row is ignored when the new list is shorter.
w5=m.page(); m.word(w5+O['W_H'],96); m.word(w5+0x7c,300)
es5=[m.entry(w5,i*48) for i in range(2)]; m.nodes[w5]['children']=es5
assert m.paint(w5)==0 and m.selected(w5)==0
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==es5[0]; passed()

# A settled swipe stores the row the user sees, not the pre-swipe selection.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96); m.word(w+0x7c,1000)
es=[m.entry(w,i*48) for i in range(10)]; m.nodes[w]['children']=es
m.paint(w); m.touch(); m.word(w+O['SCROLL_Y'],240); m.word(w+O['VIEW_ANIMATOR'],0x1234)
m.paint(w); assert m.selected(w)==0
m.word(w+O['VIEW_ANIMATOR'],0); m.paint(w); assert m.selected(w)==5
w2=m.page(); m.word(w2+O['W_H'],96); m.word(w2+0x7c,1000)
es2=[m.entry(w2,i*48) for i in range(10)]; m.nodes[w2]['children']=es2
assert m.paint(w2)==0 and m.selected(w2)==5 and m.get(w2+O['SCROLL_Y'])==192; passed()

# Position memory follows row text across a recreation, not just the index.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96); m.word(w+0x7c,1000)
es=[m.entry(w,i*48) for i in range(6)]; m.nodes[w]['children']=es
for i,e in enumerate(es): m.nodes[e]['text']='track %d'%i
m.paint(w)
for _ in range(4): assert m.call()==11
assert m.selected(w)==4
w2=m.page(); m.word(w2+O['W_H'],96); m.word(w2+0x7c,1000)
order=[4,0,1,2,3,5]
es2=[m.entry(w2,i*48) for i in range(6)]; m.nodes[w2]['children']=es2
for i,e in enumerate(es2): m.nodes[e]['text']='track %d'%order[i]
assert m.paint(w2)==0 and m.selected(w2)==0
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==es2[0]; passed()
# Rows without text fall back to the remembered index.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96); m.word(w+0x7c,1000)
es=[m.entry(w,i*48) for i in range(6)]; m.nodes[w]['children']=es
m.paint(w)
for _ in range(3): assert m.call()==11
assert m.selected(w)==3
w2=m.page(); m.word(w2+O['W_H'],96); m.word(w2+0x7c,1000)
es2=[m.entry(w2,i*48) for i in range(6)]; m.nodes[w2]['children']=es2
assert m.paint(w2)==0 and m.selected(w2)==3; passed()

# An interrupted recall glide keeps the remembered row instead of adopting a visible one.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96); m.word(w+0x7c,1000)
es=[m.entry(w,i*48) for i in range(10)]; m.nodes[w]['children']=es
m.paint(w)
for _ in range(5): assert m.call()==11
w2=m.page(); m.word(w2+O['W_H'],96); m.word(w2+0x7c,1000)
es2=[m.entry(w2,i*48) for i in range(10)]; m.nodes[w2]['children']=es2
m.glide=False
assert m.touch()==0
m.paint(w2); assert m.selected(w2)==5
w3=m.page(); m.word(w3+O['W_H'],96); m.word(w3+0x7c,1000)
es3=[m.entry(w3,i*48) for i in range(10)]; m.nodes[w3]['children']=es3
assert m.paint(w3)==0 and m.selected(w3)==5; passed()
# A wheel detent right after recreation computes its glide from the live offset.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96); m.word(w+0x7c,1000)
es=[m.entry(w,i*48) for i in range(10)]; m.nodes[w]['children']=es
m.paint(w)
for _ in range(5): assert m.call()==11
w2=m.page(); m.word(w2+O['W_H'],96); m.word(w2+0x7c,1000)
es2=[m.entry(w2,i*48) for i in range(10)]; m.nodes[w2]['children']=es2
m.glide=False
assert m.call()==11 and m.selected(w2)==6
assert m.moved()[-1][0]=='scroll_view_scroll_delta_to' and m.moved()[-1][3]==240; passed()

# A live list whose row count changes resets the selection without re-reading the table.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96); m.word(w+0x7c,1000)
es=[m.entry(w,i*48) for i in range(10)]; m.nodes[w]['children']=es
m.paint(w)
for _ in range(5): assert m.call()==11
assert m.selected(w)==5
m.nodes[w]['children']=es[:6]; m.word(w+0x7c,6*48); m.word(w+O['SCROLL_Y'],0)
m.paint(w); assert m.selected(w)==0; passed()

# Virtual music tables recall a logical row and scroll to it on recreation.
m=Machine(); w=m.page('allmusic_page','table_client')
m.word(w+0x78,48); m.word(w+0x7c,20); m.word(w+O['W_H'],96)
rows=[m.node('table_row') for _ in range(4)]
entries=[m.entry(r) for r in rows]; m.nodes[w]['children']=rows
for j,(r,e) in enumerate(zip(rows,entries)):
    m.nodes[r]['children']=[e]; m.word(r+O['W_PARENT'],w); m.word(r+0x78,j); m.word(r+4,j*48)
m.paint(w)
for _ in range(2): assert m.call()==11
assert m.selected(w)==2 and m.get(w+0x80)==48
m.rebind=None
w2=m.page('allmusic_page','table_client')
m.word(w2+0x78,48); m.word(w2+0x7c,20); m.word(w2+O['W_H'],96)
rows2=[m.node('table_row') for _ in range(4)]
entries2=[m.entry(r) for r in rows2]; m.nodes[w2]['children']=rows2
for j,(r,e) in enumerate(zip(rows2,entries2)):
    m.nodes[r]['children']=[e]; m.word(r+O['W_PARENT'],w2); m.word(r+0x78,j); m.word(r+4,j*48)
m.paint(w2); assert m.selected(w2)==2 and m.get(w2+0x80)==48
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==entries2[2]; passed()

# Home keeps its native carousel presentation and value (including touch changes).
m=Machine(); w=m.page('home_page','slide_menu'); m.word(w+0x78,1)
child=[m.entry(w),m.entry(w)]; m.nodes[w]['children']=child
assert m.paint(w)==0 and not m.strokes
assert any(c[0]=='stock_paint' for c in m.calls)
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==child[1]
m.word(w+0x78,0)
assert m.call(O['KEY_CENTER'])==11 and m.dispatched()[0][1]==child[0]; passed()
# Long-press/boot release must reach stock cleanup, never activate a menu item.
for addr in [syms['g_power_longkey'],syms['g_ingore_bootkey_flag'],0xa37c8a]:
    m.byte(addr,1); assert m.call(O['KEY_CENTER'])==0 and not m.dispatched(); m.byte(addr,0); passed()
# A quick second centre release reaches stock, whose short press toggles the screen.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1
assert m.call(O['KEY_CENTER'],gap=100)==0 and not m.dispatched()
assert m.call(O['KEY_CENTER'],gap=100)==11 and len(m.dispatched())==1; passed()
# A wheel detent ends the double-click window: the next press selects instead.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1
m.call(gap=50)
assert m.call(O['KEY_CENTER'],gap=50)==11 and len(m.dispatched())==1; passed()
# An empty menu consumes both presses; the window only arms after a real click.
m=Machine(); w=m.page()
assert m.call(O['KEY_CENTER'])==11 and not m.dispatched()
assert m.call(O['KEY_CENTER'],gap=100)==11 and not m.dispatched(); passed()
# A touch between the releases cancels the pair: the second press selects again.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1
m.call(address=HOOKS['on_wm_tsdown_before_fun'][0], gap=100)
assert m.call(O['KEY_CENTER'],gap=100)==11 and m.dispatched()[0][1]==es[0]; passed()
# A different top window cancels the pair too: no screen toggle after navigation.
m=Machine(); w=m.page('sysset_page'); m.word(w+O['W_H'],96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(O['KEY_CENTER'])==11 and len(m.dispatched())==1
w2=m.page('display_page'); m.word(w2+O['W_H'],96)
es2=[m.entry(w2,i*48) for i in range(3)]; m.nodes[w2]['children']=es2
assert m.call(O['KEY_CENTER'],gap=100)==11 and m.dispatched()[0][1]==es2[0]; passed()
# Fast same-direction detents accelerate; a slow detent or a reversal starts over.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96); m.word(w+0x7c,40*48)
es=[m.entry(w,i*48) for i in range(40)]; m.nodes[w]['children']=es
m.paint(w)
assert m.call(O['KEY_NEXT'])==11 and m.selected(w)==1
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==2
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==4
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==6
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==8
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==12
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==16
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==20
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==28
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==36
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==39
assert m.call(O['KEY_NEXT'],gap=50)==11 and m.selected(w)==39
assert m.call(O['KEY_PREV'],gap=50)==11 and m.selected(w)==38
assert m.call(O['KEY_NEXT'],gap=1000)==11 and m.selected(w)==39; passed()
# Fast detents accelerate the pixel-scroll fallback the same way.
m=Machine(); w=m.page(t='table_client')
assert m.call(gap=50)==11 and m.get(w+0x80)==48
assert m.call(gap=50)==11 and m.get(w+0x80)==96
assert m.call(gap=50)==11 and m.get(w+0x80)==192
assert m.call(gap=1000)==11 and m.get(w+0x80)==240; passed()
# A click on a clickable child selects its collected ancestor, not a stale row.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
row1=m.entry(w,0); row2=m.entry(w,96); deep=m.entry(row1,0)
m.nodes[row1]['children']=[deep]; m.nodes[w]['children']=[row1,row2]
m.paint(w); assert m.selected(w)==0
assert m.call(O['KEY_NEXT'])==11 and m.selected(w)==1
m.click(deep); assert m.selected(w)==0
m.click(m.node('button')); assert m.selected(w)==0; passed()
# Real canvas ABI, translation and clip code execute; only the LCD rectangle sink is mocked.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
e=m.entry(w,48); m.nodes[w]['children']=[e]
for name in ('canvas_get_clip_rect','canvas_set_clip_rect','canvas_set_stroke_color','canvas_stroke_rect'):
    del m.handlers[syms[name]]
m.handlers[syms['lcd_stroke_rect']]='lcd_stroke_rect'
m.word(m.lcd+0x3c,1); m.word(m.lcd+0xb0,240); m.word(m.lcd+0xb4,240)
m.word(m.canvas,7); m.word(m.canvas+4,20)
for off,val in [(0x10,10),(0x14,30),(0x18,229),(0x1c,199)]: m.word(m.canvas+off,val)
m.paint(w)
assert m.strokes[0][:4]==(8,69,238,46)
assert m.strokes[0][4:]==((10,30,220,86),0xffffffff)
assert [m.get(m.canvas+off) for off in (0x10,0x14,0x18,0x1c)]==[10,30,229,199]
assert m.get(m.lcd+O['LCD_STROKE_COLOR'])==0x12345678; passed()
# Centre and rapid wheel reversals retain the selected item during an unfinished wheel glide.
m=Machine(); w=m.page(); m.word(w+O['W_H'],96)
es=[m.entry(w,i*48) for i in range(6)]; m.nodes[w]['children']=es
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
m.paint(w); assert m.selected(w)==0 and m.strokes[0][4]==(0,0,240,96); passed()
# The actual stock filter runs first, including each screen-off lock mode.
for backlight in [0,1]:
    for mode in range(4):
        for key in [170,171,172,173,218,222,223,42]:
            results=[]
            for patched in [False,True]:
                m=Machine(patched); m.page('playing_page')
                m.byte(syms['g_backlight_status'],backlight)
                m.byte(syms['g_keylock_flag'],1); m.byte(syms['g_keylock_mode'],mode)
                results.append(m.call(key))
            assert results[0]==results[1],(backlight,mode,key,results)
            passed()
# Non-ring keys on supported pages must pass through unchanged.
for key in [0,13,170,171,222,223,0xffffffff]:
    m=Machine(); m.page(); assert m.call(key)==0 and not m.moved(); passed()
# Execute original get_direction for wraparound, thresholds, and half-turn ambiguity.
for current,previous,threshold,want in [(5,195,5,-1),(195,5,5,1),(20,20,10,0),
    (30,20,10,0),(31,20,10,-1),(9,20,10,1),(120,20,10,0),(20,120,10,0)]:
    m=Machine(); assert m.call(address=syms['get_direction'],args=(current,previous,threshold,0))==want; passed()
print(f'{checks} MIPS execution scenarios passed; toolkit services mocked, stock lock filter executed.')
