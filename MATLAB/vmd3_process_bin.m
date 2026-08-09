%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Process VMD3 Raw Binary File
% Author: Ethan Chee
% Last Edited: 11/18/2024
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
clc;
clear;
close all;


%% Changeable Parameters
BINARY_FILEPATH = "/home/shaylon/repos/ALiSM_Python_copy/vmd3-twotarget/data/radc/2026-07-21/twotarget-test.bin";
CONFIG_MODE = "2D"; % 2D or 3D
MAX_RANGE = 10; % Meters
MAX_ANGLE_RANGE = 67; % Degrees
BF1_ANGLE = 0;
BF2_ANGLE = 15;


%% CONSTANTS: DO NOT EDIT THIS SECTION
TIME_STEP = 0.13;               % Units: seconds
SAMPLE_FREQ = 1 / TIME_STEP;    % Units: Hz
HEADER_TO_PROCESS = 'RADC';
SLOW_TIME_SAMPLES = [];
BF1_SLOW_TIME_SAMPLES = [];
BF2_SLOW_TIME_SAMPLES = [];
FAST_TIME_PLOTS_INITIALIZED = false;


%% Get all frames from binary with the matching header
frames = get_frames(BINARY_FILEPATH, HEADER_TO_PROCESS, CONFIG_MODE);
%frames = frames(100:101); % Temporary... I'm too impatient. Uncomment and use if you are also impatient :).

if isempty(frames)
    error('NO FRAMES FOUND');
end

for i = 1:length(frames)
    fprintf('Processing Frame #%d/%d ...', i, length(frames));

    % Get frame cube: Samples x Chirps x Channels
    if CONFIG_MODE == "2D"
        cube = decode_radc_2d(frames{i});
    elseif CONFIG_MODE == "3D"
        cube = decode_radc_3d(frames{i});
    else
        error('INVALID CONFIG MODE. MUST BE "2D" or "3D"');
    end

    % RANGE FFT: Perform FFT across samples dimension.
    % INPUT: Samples x Chirps x Channels
    % OUTPUT: Range x Chirps x Channels
    fft_range = fft(cube, [], 1);

    % DOPPLER FFT: Perform FFT across chirps dimension
    % INPUT: Range x Chirps x Channels
    % OUTPUT: Range x Velocity x Channels
    fft_doppler = fft(fft_range, [], 2);
    fft_doppler = fftshift(fft_doppler, 2);

    % ANGLE FFT: Perform FFT across channels dimension
    % INPUT: Range x Velocity x Channels
    % OUTPUT: Range x Velocity x Angle
    fft_angle = fft(fft_doppler, 128, 3); % Zero padding of 1024 points
    fft_angle = fftshift(fft_angle, 3);

    % Average chirps of range FFT result.
    % INPUT: Range x Chirps x Channels
    % OUTPUT: Channels x Range (averaged)
    averaged_chirps = mean(fft_angle, 2);
    averaged_chirps = reshape(averaged_chirps, 128, size(averaged_chirps, 3)).';

    % Save to slow time samples (pick channel 0)
    SLOW_TIME_SAMPLES = [SLOW_TIME_SAMPLES, averaged_chirps(1, :)'];

    % BEAMFORMING
    nRx = size(fft_range, 3);
    angles = linspace(-MAX_ANGLE_RANGE, MAX_ANGLE_RANGE, 512);
    subbeam = [];
    for alpha_i = 1:length(angles)
        alpha = angles(alpha_i);
        wBF = [];
        for n = 1:nRx
            x = -pi * n * sin(deg2rad(alpha));
            real_part = cos(x);
            imag_part = sin(x);
            wBF = [wBF, real_part + 1i * imag_part];
        end
        ret = zeros(128, 32);
        for k = 1:32
            ret(:, k) = squeeze(fft_range(:, k, :)) * wBF';
        end
        ret = mean(ret, 2);
        subbeam = [subbeam, ret];
    end

    % PLOT TIME/FREQ DOMAIN OF BEAMFORMED DATA
    delta = (angles(end) - angles(1)) / length(angles);
    index0 = round((BF1_ANGLE - angles(1)) / delta);
    index1 = round((BF2_ANGLE - angles(1)) / delta);
    BF1_SLOW_TIME_SAMPLES = [BF1_SLOW_TIME_SAMPLES, subbeam(:, index0)];
    BF2_SLOW_TIME_SAMPLES = [BF2_SLOW_TIME_SAMPLES, subbeam(:, index1)];

    % % RANGE-ANGLE HEATMAP
    % rangeAngleData = sum(abs(fft_angle), 2); 
    % %rangeAngleData = max(abs(fft_angle), [], 2);
    % rangeAngleData = squeeze(rangeAngleData);
    % 
    % % Initialize fast-time plots
    % if ~FAST_TIME_PLOTS_INITIALIZED
    %     % RANGE-ANGLE HEATMAP
    %     figure;
    %     rangeAxis = linspace(0, MAX_RANGE, 128);
    %     angleAxis = linspace(-90, 90, size(rangeAngleData, 2)); % Example angle range (-90° to 90°)
    %     heatmapHandle = imagesc(angleAxis, rangeAxis, rangeAngleData);
    %     colorbar;
    %     xlabel('Angle (Degrees)');
    %     ylabel('Range (Meters)');
    %     title('Range-Angle Heatmap');
    %     set(gca, 'YDir', 'normal'); % Flip Y-axis to align with conventional heatmap
    %     colormap(jet);
    % 
    %     FAST_TIME_PLOTS_INITIALIZED = true;
    % % Update fast-time plots
    % else
    %     % RANGE-ANGLE HEATMAP
    %     set(heatmapHandle, 'CData', rangeAngleData); % Update heatmap data
    % end
    % 
    % % Refresh the fast-time plot(s)
    % drawnow;

    fprintf('Done!\n');
end

%% Plot Time Domain
plot_time_domain(SLOW_TIME_SAMPLES', TIME_STEP, 'ALL');
plot_time_domain(BF1_SLOW_TIME_SAMPLES', TIME_STEP, sprintf('BF1 (%d Deg)', BF1_ANGLE));
plot_time_domain(BF2_SLOW_TIME_SAMPLES', TIME_STEP, sprintf('BF2 (%d Deg)', BF2_ANGLE));

%% Plot Frequency Domain
plot_freq_domain(SLOW_TIME_SAMPLES', SAMPLE_FREQ, 'ALL');
plot_freq_domain(BF1_SLOW_TIME_SAMPLES', SAMPLE_FREQ, sprintf('BF1 (%d Deg)', BF1_ANGLE));
plot_freq_domain(BF2_SLOW_TIME_SAMPLES', SAMPLE_FREQ, sprintf('BF2 (%d Deg)', BF2_ANGLE));


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
% Pass in a RADC 2D frame to decode
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

%% plot_time_domain
% Plot all channels
function plot_time_domain(slow_time_samples, time_step, plot_title)
    data = mean(slow_time_samples, 2);
    data = data(2:length(data)); % First index always bad data?

    % Remove DC Offset
    data_mean = mean(data);
    for j = 1:length(data)
        data(j) = data(j) - data_mean;
    end

    % Calculate time interval
    time_length = length(data) * time_step;
    x_time = time_step:time_step:time_length;
    y_time = data(1:length(x_time)).';

    figure;
    hold on;
    plot(x_time, y_time, 'DisplayName', sprintf('Signal%d', 1));
    title(sprintf('Time Domain %s', plot_title));
    xlabel('Time (s)');
    ylabel('Magnitude (mV)');
    grid on;
    legend show;
end

%% plot_freq_domain
% Just plot one channel
function plot_freq_domain(slow_time_samples, sample_freq, plot_title)
    data = mean(slow_time_samples, 2);
    data = data(2:length(data)); % First index always bad data?

    % Remove DC Offset
    data_mean = mean(data);
    for i = 1:length(data)
        data(i) = data(i) - data_mean;
    end

    % Zero padding to increase resolution
    data = [data; zeros(1024, 1)];

    % Perform FFT to get frequency domain
    num_samples = length(data);
    fft_freq = abs(fft(data)); % Take magnitude. Can change to angle?
    y_freq = fft_freq(1:ceil(num_samples/2));
    x_freq = sample_freq * (0:ceil(num_samples/2-1)) / num_samples;
    
    % Plot Frequency Domain
    figure;
    plot(x_freq, y_freq);
    title(sprintf('Frequency Domain %s', plot_title));
    xlabel('Frequency (Hz)');
    ylabel('Magnitude');
    grid on;
end
