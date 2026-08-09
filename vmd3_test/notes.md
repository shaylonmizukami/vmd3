# 1
What type of data is being used for the heatmap range


Take the raw unaveraged channel data (butterworth filter, order of 6, cutoff filter of 1 Hz or less (low pass filter))
Plot the time domain I/Q data
Plot the I/Q circle data
Take RFFT from this and compare it to the VMD3 RFFT data from the FPGA
Validate this and see if we can improve it (noise and such)


NOTEBOOK
vmd3-01:
just plot the 4 radc channels in I/Q time domain individually


NOTEBOOK SETUP
1. Import data
2. Setup radc frame (channel 1, 2, 3, 4 individually on data frame)
3. Filter data, generate I/Q time domain plots, generate I/Q circle plot
4. Unwrap and get displacement, and get fft on time domain and displacement waveform
