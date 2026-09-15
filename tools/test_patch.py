#!/usr/bin/env python3
"""Execute the actual patched MIPS callback with stock filter and mocked UI services.
Requires unicorn==2.1.4. Does not emulate the entire device or flash hardware.
"""
import json, pathlib, struct, sys
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
from build import segments, symbols, HOOK
B=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'build')
manifest=json.loads((B/'manifest.json').read_text())
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
            # Protect the injected executable payload from accidental data writes.
            if v==0xb00000: self.u.mem_protect(start,end-start,5)
        self.u.mem_map(0x1000000,0x200000)
        self.u.mem_map(0x70000000,0x10000)
        self.next=0x1001000; self.nodes={}; self.calls=[]; self.animating=0; self.pressed=0
        self.top=0; self.wm=0x1000000; self.event=0x1000100
        self.handlers={}
        for name in manifest['functions']: self.handlers[syms[name]]=name
        self.handlers[syms['reset_poweroptions_timer']]='reset_poweroptions_timer'
        self.u.hook_add(UC_HOOK_CODE,self.hook)
        for name in manifest['globals']: self.byte(syms[name],0)
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
        self.word(a+0x0c,240); self.word(a+0x78,48); self.word(a+0x7c,960 if t=='scroll_view' else 100)
        self.byte(a+0x91,1)
        return a
    def entry(self,parent,y=0,index=None,t='list_item'):
        """A leafless tap target: emitter with one EVT_CLICK item, widget_y offset y, height 48."""
        a=self.node(t)
        em=self.alloc(4); it=self.alloc(0x28)
        self.word(a+0x60,em); self.word(em,it); self.word(it+8,0x10c)
        self.word(a+0x48,parent); self.word(a+0x04,y); self.word(a+0x0c,48)
        if index is not None: self.word(a+0x78,index)
        return a
    def focused(self,w): return self.u.mem_read(w+0x24,1)[0]&0x80
    def hook(self,u,address,size,_):
        if address not in self.handlers: return
        name=self.handlers[address]
        assert u.reg_read(UC_MIPS_REG_T9)==address, (name,'PIC call missing t9')
        a,b,c,d=[u.reg_read(r) for r in REGS]
        n=self.nodes.get(a,{})
        self.calls.append((name,a,b,c))
        if name=='window_manager': ret=self.wm
        elif name=='window_manager_get_top_window': ret=self.top
        elif name=='window_manager_is_animating': ret=self.animating
        elif name=='window_manager_get_pointer_pressed': ret=self.pressed
        elif name=='widget_get_visible': ret=n.get('visible',0)
        elif name=='widget_get_type': ret=self.string(n.get('type',''))
        elif name=='widget_get_prop_str': ret=self.string(n.get(self.text(b),''))
        elif name in ('widget_get_prop_bool','widget_get_prop_int'): ret=n.get(self.text(b),c)
        elif name=='widget_count_children': ret=len(n['children'])
        elif name=='widget_get_child': ret=n['children'][b] if b<len(n['children']) else 0
        elif name=='widget_set_focused_internal':
            cur=struct.unpack('<H',self.u.mem_read(a+0x24,2))[0]
            self.u.mem_write(a+0x24,struct.pack('<H',(cur|0x80) if b else (cur&~0x80))); ret=0
        elif name=='pointer_event_init': ret=a
        elif name=='widget_dispatch_async': ret=0
        elif name=='table_client_set_yoffset': self.word(a+0x80,b); ret=0
        elif name=='table_client_scroll_to': self.word(a+0x80,b); ret=0
        elif name=='scroll_view_set_offset': self.word(a+0x80,b); self.word(a+0x84,c); ret=0
        elif name=='scroll_view_scroll_delta_to':
            self.word(a+0x80,self.get(a+0x80)+b); self.word(a+0x84,self.get(a+0x84)+c); ret=0
        else: ret=0
        # Clobber caller-saved registers to catch accidental ABI assumptions.
        for r in [UC_MIPS_REG_V1,*REGS,UC_MIPS_REG_T0,UC_MIPS_REG_T1,UC_MIPS_REG_T2,
                  UC_MIPS_REG_T3,UC_MIPS_REG_T4,UC_MIPS_REG_T5,UC_MIPS_REG_T6,
                  UC_MIPS_REG_T7,UC_MIPS_REG_T8,UC_MIPS_REG_T9]:
            u.reg_write(r,0xdeadbeef)
        u.reg_write(UC_MIPS_REG_V0,ret&0xffffffff)
        u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
    def call(self,key=173,address=HOOK,args=None):
        self.calls=[]; self.word(self.event+0x18,key)
        self.word(self.event,0x114)
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
    def moved(self): return [x for x in self.calls if x[0] in ('scroll_view_scroll_delta_to','scroll_view_set_offset','table_client_scroll_to','table_client_set_yoffset','slide_menu_scroll_to_next','slide_menu_scroll_to_prev')]
    def dispatched(self): return [x for x in self.calls if x[0]=='widget_dispatch_async']

checks=0
def passed():
    global checks
    checks+=1

for t,off in [('scroll_view',0x84),('table_client',0x80)]:
    m=Machine(); w=m.page(t=t)
    for _ in range(20): assert m.call()==11
    assert m.get(w+off)==min(20*manifest['ring_step_pixels'],720 if t=='scroll_view' else 4560)
    assert m.call(172)==11 and m.moved()
    for _ in range(120): m.call(172)
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
assert m.call(172)==11 and m.moved()[0][0]=='slide_menu_scroll_to_prev'; passed()
m=Machine(); hidden=m.node(visible=0); shown=m.node(); pages=m.node('pages',children=[hidden,shown],active=1)
m.top=m.node('window','artistinfo_page',[pages]); assert m.call()==11 and m.moved()[0][1]==shown; passed()
m.nodes[hidden]['visible']=1
assert m.call()==11 and m.moved()[0][1]==shown; passed()
m.top=m.node('window','sysset_page',[hidden,shown]); assert m.call()==11 and not m.moved(); passed()
for attribute in ['visible','enable']:
    m=Machine(); w=m.page(); m.nodes[w][attribute]=0; assert m.call()==11 and not m.moved(); passed()
# An in-flight scroll animation is retargeted by the animated glide, not torn down.
m=Machine(); w=m.page(); m.word(w+0x84,100)
assert m.call()==11 and m.moved()[0][0]=='scroll_view_scroll_delta_to' and m.moved()[0][3]==48
assert m.get(w+0x84)==148 and m.get(w+0xe8)==0; passed()

# Ring navigation focuses an entry and glides it fully into view one detent at a time.
m=Machine(); w=m.page(); m.word(w+0x0c,96); m.word(w+0x7c,1000)
entries=[m.entry(w,i*48) for i in range(5)]
m.nodes[w]['children']=entries
assert m.call()==11 and m.focused(entries[0]) and not m.moved()
assert m.call()==11 and m.focused(entries[1]) and not m.moved()
assert m.call()==11 and m.focused(entries[2]) and m.get(w+0x84)==48
assert m.moved()[0][0]=='scroll_view_scroll_delta_to' and m.moved()[0][3]==48; passed()
# A short center press dispatches the native async EVT_CLICK to the focused entry.
assert m.call(171)==11 and m.dispatched()[0][1]==entries[2]; passed()
# ... and is ignored (stock play/pause) until the ring has focused something.
m2=Machine(); w2=m2.page(); m2.word(w2+0x0c,96); e=m2.entry(w2); m2.nodes[w2]['children']=[e]
assert m2.call(171)==0 and not m2.dispatched(); passed()

# table_client selection is tracked by row index and re-bound after scrolling.
m=Machine(); w=m.page('sysset_page','table_client')
m.word(w+0x78,48); m.word(w+0x7c,3); m.word(w+0x0c,96)
rows=[m.entry(w,index=i) for i in range(3)]
m.nodes[w]['children']=rows
assert m.call()==11 and m.focused(rows[0]) and m.get(w+0x80)==0
assert m.call()==11 and m.focused(rows[1]) and m.get(w+0x80)==0
assert m.call()==11 and m.focused(rows[2]) and m.get(w+0x80)==48
assert m.call(171)==11 and m.dispatched()[0][1]==rows[2]; passed()

# slide_menu center activates the child at its native value (@0x78).
m=Machine(); w=m.page('home_page','slide_menu'); m.word(w+0x78,1)
child=[m.node('slide_item'),m.entry(w)]
m.nodes[w]['children']=child
assert m.call(171)==11 and m.dispatched()[0][1]==child[1]; passed()
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
for key in [0,13,170,171,218,222,223,0xffffffff]:
    m=Machine(); m.page(); assert m.call(key)==0 and not m.moved(); passed()
# Execute original get_direction for wraparound, thresholds, and half-turn ambiguity.
for current,previous,threshold,want in [(5,195,5,-1),(195,5,5,1),(20,20,10,0),
    (30,20,10,0),(31,20,10,-1),(9,20,10,1),(120,20,10,0),(20,120,10,0)]:
    m=Machine(); assert m.call(address=syms['get_direction'],args=(current,previous,threshold,0))==want; passed()
print(f'{checks} MIPS execution scenarios passed; toolkit services mocked, stock lock filter executed.')
