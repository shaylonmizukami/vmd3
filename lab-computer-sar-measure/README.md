CONNECTING TO VMD3 ON THIS LAPTOP

1. Connect the adapter to the 2nd USB-C port (next to HDMI port) on the left side of the laptop.
   Connect the power cable to the radar and connect the ethernet cable to the ethernet port on the adapter.

2. Run the "run_setup.bat" file as administrator. This will run the "setup_radar.ps1" file.
   Should see the output like the following:
''' 
[*] Checking for adapter 'Ethernet'...  
[OK] Adapter 'Ethernet' found.  
[*] Enabling 'Ethernet'...   
[OK] 'Ethernet' enabled.  
[*] Assigning 192.168.100.1/24 to 'Ethernet'...   
[OK] IP 192.168.100.1 already assigned. 
[*] Opening UDP 4567 in Windows Firewall...  
[OK] Firewall rule 'VMD3 Radar UDP 4567' already exists.  
[*] Waiting for ethernet link...  
[OK] Ethernet link active.  
[*] Pinging radar at 192.168.100.201...   
[OK] Radar is responding at 192.168.100.201.  
 
[OK] All checks passed.  
'''
   Radar is ready to use if all the checks passed.
   If any step shows [X] in red instead of [OK], that line tells you what's wrong


OPENING THE PROJECT

3. Open the project folder in VS Code:
   - Open VS Code.
   - File > Open Folder > "C:/My Computer/vmd3/test" (the folder that contains measure.py, lib folder, and notebook).

4. Make sure the correct Python environment is selected:
   - Open any terminal in VS Code (Terminal > New Terminal). You should see "(.venv)" at the start of the prompt line.
   - If you do not see "(.venv)", press Ctrl+Shift+P, type "Python: Select Interpreter", and choose the one located in the ".venv" folder inside this project.


FOR GUI

5. Use this to point the radar and confirm the target is visible before recording.
   - In the VS Code terminal (with "(.venv)" showing), run: python measure.py
   - The GUI will show.


RECORDING DATA (NOTEBOOK)

6. Open the notebook file (the ".ipynb" file).

7. Run the cells top to bottom with Shift+Enter:
   - Cell 1: loads the code (run once).
   - Cell 2: settings you can edit (session name, streams, frames per position).
   - Cell 3: connects to the radar (run once).
   - Cell 4: records one position. Set the position at the top of the cell, then run cell. Repeat for each position.
   - Cell 5: disconnects when finished.

   (Each cell has notes above it explaining what to change and when to re-run it.)


CONVERTING DATA TO CSV

8. To convert a recorded ".bin" file to CSV, use the conversion cell in the notebook.
   Set the file to convert and the output location at the top of that cell, then run cell.