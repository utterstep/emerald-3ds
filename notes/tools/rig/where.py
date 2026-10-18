"""where.py 'LINE; LINE; ...' : run these screen-script lines on the build and print the
player's map coordinates and facing (rig debugging; the build's symbols)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import riglib, screens  # noqa: E402
rom = os.environ.get("ROM", str(riglib.DEFAULT_BUILD))
syms = riglib.build_syms(rom)
lines = screens.expand([l.strip() for l in " ".join(sys.argv[1:]).split(";")], "build")
script = "\n".join(riglib.resolve(l.replace("{SAVES}", str(riglib.RIG / "saves")), syms) for l in lines) + "\n"
script += "r8 %x\n" % (syms["gPlayerAvatar"] + 5)
out, _ = riglib.run_rig(rom, script)
oid = int(out.strip().split()[-1], 16)
base = syms["gObjectEvents"] + oid * 0x24
out, _ = riglib.run_rig(rom, script + "r16 %x\nr16 %x\nr8 %x\n" % (base + 0x10, base + 0x12, base + 0x18))
v = [int(x.split(": ")[1], 16) for x in out.strip().splitlines()[-3:]]
print("x=%d y=%d facing=%d (1 down 2 up 3 left 4 right)" % (v[0] - 7, v[1] - 7, v[2] & 0xF))
