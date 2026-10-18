// Scratch-only stand-ins so the patched tree links as a GBA ROM for emulator checks.
#include "global.h"
void Port_SetBirchDebugEx(u32 a, u32 b, u32 c, u32 d, u32 e) {}
u16 LocalSession_IsEnabled(void) { return FALSE; }
u16 LocalSession_Start(void) { return FALSE; }
u16 LocalSession_CanEnter(void) { return FALSE; }
void LocalSession_Leave(void) {}
void LocalSession_Wait(void) {}
void LocalSession_Update(void) {}
