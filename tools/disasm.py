#!/usr/bin/env python3
"""Disassemble a stock demo symbol/address and annotate its primary GOT loads."""
import pathlib,re,struct,subprocess,sys
p=pathlib.Path('work/root/release/bin/demo'); b=p.read_bytes()
symbols={}; sizes={}
for line in subprocess.check_output(['readelf','-Ws',str(p)],text=True).splitlines():
 s=line.split()
 if len(s)>=8 and s[0].endswith(':'):
  try: a=int(s[1],16); size=int(s[2])
  except ValueError: continue
  if a: symbols[a]=s[7]; sizes[s[7]]=(a,size)
def offset(a):
 return a-(0x400000 if a<0x912410 else 0x410000)
def word(a): return struct.unpack_from('<I',b,offset(a))[0]
def desc(a):
 if a in symbols: return symbols[a]
 o=offset(a)
 if 0<=o<len(b):
  s=b[o:o+100].split(b'\0')[0]
  if s and all(32<=x<127 for x in s): return repr(s.decode())
 return hex(a)
a,n=sizes.get(sys.argv[1],(0,0))
if not a: a=int(sys.argv[1],0); n=int(sys.argv[2],0)
for line in subprocess.check_output(['llvm-objdump','-d','--no-show-raw-insn',f'--start-address={a}',f'--stop-address={a+n}',str(p)],text=True).splitlines():
 m=re.search(r'lw\s+\$\w+, (-?0x[0-9a-f]+)\(\$gp\)',line)
 if m:
  v=word(0xa26cc0+int(m[1],0)); line+=' # '+desc(v)
 print(line)
