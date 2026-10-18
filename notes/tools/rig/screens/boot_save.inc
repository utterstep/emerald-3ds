# From power-on to the main menu with the save already given (sav ...): START skips
# the intro and the title screen's phases; at the main menu START does nothing.
run 1
# The build's CONTINUE window expands {STR_VAR_1..3} that its main_menu.c never fills
# (a known gap: it hangs, see the continue screen); empty strings let it draw.
build: w8 {gStringVar1} ff
build: w8 {gStringVar2} ff
build: w8 {gStringVar3} ff
run 300
repeat 10 tap START 30
