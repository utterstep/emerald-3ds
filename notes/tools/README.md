# Emulator and code-map tools from the cloud session

Scratch tooling used to check the Japanese build without a 3DS (round two, on
feature/japanese-build 1f87d15). Code only: no ROM, saves, screenshots or
disassembly. The scripts were written for a Linux container and some hold its
scratch paths (`S=` near the top, `riglib.py`); set them to your own folders.

- `rig/`: a GBA build of a staged tree for emulator checks (`build_gba.sh`: sets the
  port-only units aside, restores the decomp's audio and flash code, `make modern`),
  a headless mGBA driver (`mgbarig.c`; build with `gcc mgbarig.c -lmgba -lpng`),
  test saves made by the game's own code (`make_saves.py`, `rig_fill.c`), input
  scripts that reach 24 screens in both the cartridge and the build (`screens.py`,
  `screens/`), and a compile check of the 3DS units with a plain arm-none-eabi-gcc
  and the libctru headers (`ctr_compile_check.sh`, `ctr/stub`). Needs
  gcc-arm-none-eabi, libnewlib-arm-none-eabi, libmgba-dev, libpng-dev, Pillow.
  `rig/README.md` has the details.
- `syms/`: maps the Japanese ROM's functions and data to the decomp's symbols by
  matching against a vanilla English build made with agbcc (`bin/match.py`,
  `validate.py`, `report.py`; `jpdis.sh NAME --side` shows a function in both).
  It is weak on short strings in changed data (the Japanese manifest's offsets
  were right in every case checked). `syms/README.md` has the method and numbers.
