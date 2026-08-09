%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Process VMD3 Raw Binary File
% Author: Ethan Chee
% Last Edited: 11/18/2024
% Modified: slow-time phase displacement extraction + I/Q diagnostics
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
clc;
clear;
close all;


%% Changeable Parameters
BINARY_FILEPATH = "~/repos/ALiSM_Python_copy/vmd3_test/data/radc/2026-05-26/plate_7p5m_1p6mm_0p2hz_rset1.bin";
CONFIG_MODE = "2D"; % 2D or 3D
MAX_RANGE = 10; % Meters
MAX_ANGLE_RANGE = 67; % Degrees


%% CONSTANTS: DO NOT EDIT THIS SECTION
TIME_STEP = 0.13;               % Units: seconds
SAMPLE_FREQ = 1 / TIME_STEP;    % Units: Hz
HEADER_TO_PROCESS = 'RADC';


%% Get all frames from binary with the matching header
frames = get_frames(BINARY_FILEPATH, HEADER_TO_PROCESS, CONFIG_MODE);
%frames = frames(100:101); % Temporary... I'm too impatient. Uncomment and use if you are also impatient :).

if isempty(frames)
    error('NO FRAMES FOUND');
end

% Storage for the slow-time complex signal at the target's range bin
slow_time_signal = zeros(1, length(frames));
target_range_bin = [];   % will be picked from the first frame

for i = 1:length(frames)
    fprintf('Processing Frame #%d/%d ...', i, length(frames));

    % Decode RADC frame
    if CONFIG_MODE == "2D"
        cube = decode_radc_2d(frames{i});
    else
        cube = decode_radc_3d(frames{i});
    end

    % Range FFT only (across samples dimension)
    % cube: Samples x Chirps x Channels  →  Range x Chirps x Channels
    fft_range = fft(cube, [], 1);

    % Average across chirps and channels to get a clean range profile
    range_profile = mean(mean(abs(fft_range), 3), 2);  % (Range x 1)

    % On the first frame, find which range bin the target lives in.
    % Skip the first ~10 bins to avoid TX-RX leakage.
    if isempty(target_range_bin)
        leakage_bins_to_skip = 10;
        [~, idx] = max(range_profile(leakage_bins_to_skip+1:end));
        target_range_bin = idx + leakage_bins_to_skip;
        fprintf('\n>> Target locked at range bin %d (%.2f m)\n', ...
                target_range_bin, ...
                (target_range_bin - 1) * MAX_RANGE / size(fft_range, 1));
    end

    % Extract the complex value at the target range bin,
    % averaged across all chirps (to get one complex sample per frame),
    % and across all RX channels.
    complex_at_target = mean(mean(fft_range(target_range_bin, :, :), 2), 3);
    slow_time_signal(i) = complex_at_target;

    fprintf('Done!\n');
end

%% Convert phase to displacement
LAMBDA = 3e8 / 61.6e9;   % wavelength at center frequency, ~4.86 mm
phase_raw = angle(slow_time_signal);
phase_unwrapped = unwrap(phase_raw);
% Remove linear trend (residual range bin offset / slow drift)
phase_detrended = detrend(phase_unwrapped);
displacement_mm = -phase_detrended * LAMBDA / (4*pi) * 1000;  % in millimeters

%% Plot displacement vs time
t = (0:length(slow_time_signal)-1) * TIME_STEP;
figure;
plot(t, displacement_mm, 'LineWidth', 1.2);
xlabel('Time (s)'); ylabel('Displacement (mm)');
title('Target displacement (from slow-time phase)');
grid on;

%% Plot magnitude vs time (sanity check on signal strength)
figure;
plot(t, abs(slow_time_signal), 'LineWidth', 1.2);
xlabel('Time (s)'); ylabel('|s[n]|');
title('Target reflection magnitude over time');
grid on;

%% Plot I and Q components of the slow-time signal
I_component = real(slow_time_signal);
Q_component = imag(slow_time_signal);

figure;
hold on;
plot(t, I_component, 'LineWidth', 1.2, 'DisplayName', 'I (real)');
plot(t, Q_component, 'LineWidth', 1.2, 'DisplayName', 'Q (imag)');
xlabel('Time (s)'); ylabel('Amplitude');
title('Slow-time signal: I and Q components at target range bin');
legend show;
grid on;

%% I-Q constellation plot
figure;
plot(I_component, Q_component, '.', 'MarkerSize', 8);
axis equal;
xlabel('I (real)'); ylabel('Q (imag)');
title('I/Q constellation at target range bin');
grid on;

%% FFT of displacement signal
N_pad = 4096;
disp_fft = abs(fft(displacement_mm - mean(displacement_mm), N_pad));
freqs = (0:N_pad-1) * SAMPLE_FREQ / N_pad;
half = 1:floor(N_pad/2);

figure;
plot(freqs(half), disp_fft(half), 'LineWidth', 1.2);
xlabel('Frequency (Hz)'); ylabel('Magnitude');
title('Displacement spectrum');
xlim([0, 2]);   % zoom into the relevant range for 0.3 Hz motion
grid on;

%%
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% HELPER FUNCTIONS BELOW
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% get_frames
% Get frames from binary
function frames = get_frames(filepath, header, CONFIG_MODE)
    % Open file
    fd = fopen(filepath, 'rb');
    if fd == -1
        error('Failed to open raw binary file.');
    end

    % Read all bytes
    rawData = fread(fd, Inf, 'uint8');
    fclose(fd);

    % Find all indices where the header sequence occurs
    header_to_search = uint8(header);
    indices = strfind(rawData', header_to_search); % Transpose data for compatibility

    frames = {};
    for index = indices
        payloadLength = uint8(rawData(index+4:index+7)');
        payloadLength = typecast(payloadLength, 'uint32');

        % Verify 2D/3D
        if CONFIG_MODE == "2D" && payloadLength == 131072
            payload = uint8(rawData(index+8:index+8+payloadLength-1));
        elseif CONFIG_MODE == "3D" && payloadLength == 196608
            payload = uint8(rawData(index+8:index+8+payloadLength-1));
        else
            continue
        end

        % Verify that header does not appear in payload
        indices = strfind(payload', header_to_search);
        if length(indices) > 0
            continue
        end

        % This is a valid frame
        frames{end + 1} = payload;
    end
end

%% decode_radc_2d
% Pass in a RADC 2D frame to decode
function cube = decode_radc_2d(frame)
    % Sanity check
    if length(frame) ~= 131072
        length(frame)
        error('INVALID FRAME LENGTH FOR 2D MODE');
    end

    channel_i = cell(1, 4);
    channel_q = cell(1, 4);

    % Split into individual I/Q channels
    for sweep = 0:63
        % I Channels
        for i = 0:3
            for size = (i*512+2):4:(i*512+513)
                offset = sweep * 2048 + size;
                value = typecast(uint8(frame(offset+1:offset+2)), 'int16');
                channel_i{i+1} = [channel_i{i+1}, value];
            end
        end
        % Q Channels
        for i = 0:3
            for size = (i*512):4:(i*512+511)
                offset = sweep * 2048 + size;
                value = typecast(uint8(frame(offset+1:offset+2)), 'int16');
                channel_q{i+1} = [channel_q{i+1}, value];
            end
        end
    end

    % Convert everything to complex
    channel_complex = cell(1, 4);
    for i = 1:4
        channel_complex{i} = complex(channel_i{i}, channel_q{i});
    end

    % Transform into cube: Samples x Chirps x Channels
    cube = zeros(128, 64, 4);
    for i = 1:4
        cube(:, :, i) = reshape(channel_complex{i}, [128, 64]);
    end
end

%% decode_radc_3d
% Pass in a RADC 3D frame to decode
function cube = decode_radc_3d(frame)
    % Sanity check
    if length(frame) ~= 196608
        length(frame)
        error('INVALID FRAME LENGTH FOR 3D MODE');
    end

    channel_i = cell(1, 12);
    channel_q = cell(1, 12);

    % Split into individual I/Q channels
    for sweep = 0:31
        % I Channels
        for i = 0:11
            for size = (i*512+2):4:(i*512+513)
                offset = sweep * 2048 + size;
                value = typecast(uint8(frame(offset+1:offset+2)), 'int16');
                channel_i{i+1} = [channel_i{i+1}, value];
            end
        end
        % Q Channels
        for i = 0:11
            for size = (i*512):4:(i*512+511)
                offset = sweep * 2048 + size;
                value = typecast(uint8(frame(offset+1:offset+2)), 'int16');
                channel_q{i+1} = [channel_q{i+1}, value];
            end
        end
    end

    % Convert everything to complex
    channel_complex = cell(1, 12);
    for i = 1:12
        channel_complex{i} = complex(channel_i{i}, channel_q{i});
    end

    % Transform into cube: Samples x Chirps x Channels
    cube = zeros(128, 32, 12);
    for i = 1:12
        cube(:, :, i) = reshape(channel_complex{i}, [128, 32]);
    end
end
