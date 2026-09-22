SECTIONS {
  . = 0xb00000;
  .text : { *(.text*) }
  .rodata : { *(.rodata*) }
  /* Zero-filled writable cell; the builder maps it R/W inside the 64K payload window. */
  .scratch 0xb0f000 (NOLOAD) : { *(.scratch) }
  /DISCARD/ : { *(.comment) *(.note*) *(.pdr) *(.mdebug*) *(.MIPS.abiflags) *(.reginfo) }
}
