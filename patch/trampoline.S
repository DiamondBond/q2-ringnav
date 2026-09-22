.set noreorder
.text
/* All four audited stock PIC prologues resolve the same GOT base. */
.macro resume name, address
.globl stock_\name\()_trampoline
stock_\name\()_trampoline:
    lui $gp, 0xa2
    ori $gp, $gp, 0x6cc0
    j \address
    nop
.endm
resume keyup, 0x4e85d4
resume touch, 0x4e8bdc
resume paint, 0x6596ac
resume dispatch, 0x65e0f8
