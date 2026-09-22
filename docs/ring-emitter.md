# Q2 wheel emitter reference

Stock V1.32, from `llvm-objdump` of the work root. `encoderknob_thread_run` (`0x6256a0`) is the sysfs notifier thread; the rotation handler that follows it (`0x6258e0`, unnamed in the symbol table) calls `get_direction` (`0x62587c`) and posts key events 172/173 into the main loop. The payload hooks `on_wm_keyup_before_fun` and treats those releases as wheel detents.
