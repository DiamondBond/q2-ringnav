.set noreorder
.text
.globl stock_keyup_trampoline
stock_keyup_trampoline:
    lui $gp, 0xa2
    ori $gp, $gp, 0x6cc0
    j 0x4e85d4
    nop
