import glob
import os
import sys

# Find the most recent scan_0cm.bin under data/, or take a path argument
if len(sys.argv) > 1:
    path = sys.argv[1]
else:
    matches = glob.glob('data/testdatafolder/bins/scan_0cm.bin', recursive=True)
    if not matches:
        print('No scan_0cm.bin found under data/. Given path?')
        sys.exit(1)
    path = max(matches, key=os.path.getmtime)  # newest

print(f'Checking: {path}')
data = open(path, 'rb').read()
print(f'File size: {len(data)} bytes ({len(data)/1e6:.2f} MB)')
for h in (b'RADC', b'RFFT', b'DONE'):
    print(f'  {h.decode()}: {data.count(h)} occurrences')