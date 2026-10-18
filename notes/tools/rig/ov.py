"""ov.py OUT.png NAME... : one small montage of the latest shots of these screens (rig debugging)."""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import riglib
fs, labs = [], []
for n in sys.argv[2:]:
    for t in ['jp', 'build']:
        for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), f'shots/{t}/{n}/*.png')), key=os.path.getmtime):
            fs.append(f); labs.append(f'{t}:{n}/' + os.path.basename(f))
riglib.montage(sys.argv[1], fs, 6, labs, scale=1)
