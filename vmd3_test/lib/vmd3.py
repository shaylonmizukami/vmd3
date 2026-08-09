from enum import Enum
import socket
import sys

import numpy as np

class RdotConfig(Enum):
    DISABLED = 0
    RADC = 0x01
    RFFT = 0x02
    RMRD = 0x04
    PDAT = 0x08
    TDAT = 0x10
    DONE = 0x20

class VMD3:
    def __init__(self, standalone=False, tcp_ip='192.168.100.201', tcp_port=6172, udp_ip='0.0.0.0', udp_port=4567):
        if standalone:
            return
        
        self.tcp_ip = tcp_ip
        self.tcp_port = tcp_port
        self.udp_ip = udp_ip
        self.udp_port = udp_port

        # TCP
        self.sockTCP = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sockTCP.connect((self.tcp_ip, self.tcp_port))
        except:
            print(f'[VMD3] Error while connecting with TCP/IP socket {self.tcp_ip}:{self.tcp_port}')
            sys.exit(1)
        print('[VMD3] Connected to TCP/IP')

        # UDP
        self.sockUDP = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sockUDP.bind((self.udp_ip, self.udp_port))
        except:
            print(f'[VMD3] Error while connecting with UDP socket {self.udp_ip}:{self.udp_port}')
            sys.exit(1)
        print('[VMD3] Connected to UDP')

    def connect(self):
        header = bytes("INIT", 'utf-8')
        payloadlength = (0).to_bytes(4, byteorder='little')
        cmd_frame = header + payloadlength
        self.send_tcp(cmd_frame)
        resp_frame = self.recv_tcp()
        if resp_frame[8] != 0:
            print('[VMD3] Error: Command not acknowledged')
            sys.exit(1)
        print('[VMD3] Connected to VMD3')

    def disconnect(self):
        payloadlength = (0).to_bytes(4, byteorder='little')
        header = bytes("GBYE", 'utf-8')
        cmd_frame = header + payloadlength
        self.send_tcp(cmd_frame)
        response_gbye = self.recv_tcp()
        if response_gbye[8] != 0:
            print('[VMD3] Error during disconnecting with V-MD3')
            return False

        self.sockTCP.close()
        self.sockUDP.close()
        print('[VMD3] Disconnected')
        return True

    def set_rset_config(self, rset_config):
        if rset_config > 8:
            print('[VMD3] Invalid RSET config')
            self.disconnect()
            sys.exit(1)

        header = bytes("RSET", 'utf-8')
        payloadlength = (4).to_bytes(4, byteorder='little')
        max_range = rset_config.to_bytes(4, byteorder='little')
        cmd_frame = header + payloadlength + max_range
        self.send_tcp(cmd_frame)
        resp_frame = self.recv_tcp()
        if resp_frame[8] != 0:
            print('[VMD3] Error: Command not acknowledged')
            self.disconnect()
            sys.exit(1)
        print('[VMD3] RSET OK')

    def set_output_config(self, rdot_configs=[]):
        rdot_val = 0
        for rdot in rdot_configs:
            rdot_val += rdot.value

        header = bytes("RDOT", 'utf-8')
        payloadlength = (4).to_bytes(4, byteorder='little')
        datarequest = rdot_val.to_bytes(4, byteorder='little')
        cmd_frame = header + payloadlength + datarequest
        self.send_tcp(cmd_frame)
        resp_frame = self.recv_tcp()
        print('[VMD3] RDOT OK')

    def read_frame(self, header_requested):
        packageLength = 1500
        while True:
            data = self.recv_udp()
            if data[0:4] != header_requested:
                continue

            respLength = int.from_bytes(data[4:8], byteorder='little')
            while len(data) < respLength:
                packageData = self.recv_udp()
                data += packageData

            if data[0:4] != header_requested or respLength != len(data[8:]):
                continue

            return data
         
    def send_tcp(self, frame):
        self.sockTCP.send(frame)

    def recv_tcp(self):
        msg_len = 9
        max_msg_size = 8

        resp_frame = bytearray(msg_len)
        pos = 0
        while pos < msg_len:
            resp_frame[pos:pos + max_msg_size] = self.sockTCP.recv(max_msg_size)
            pos += max_msg_size
        return resp_frame

    def recv_udp(self):
        packageLength = 1500
        adc_data, adr = self.sockUDP.recvfrom(packageLength)
        return adc_data

    def decode_radc_2d(self, frame):
        if len(frame) != 131072:
            return None

        channel_i = [[], [], [], []]
        channel_q = [[], [], [], []]

        # Split to individual I/Q channels
        for sweep in range(0, 64):
            for i in range(0, 4):
                for size in range(i*512+2, i*512+513, 4):
                    offset = sweep * 2048 + size
                    channel_i[i].append(int.from_bytes(frame[offset:offset + 2], byteorder='little', signed=True))
            for i in range(0, 4):
                for size in range(i*512, i*512+511, 4):
                    offset = sweep * 2048 + size
                    channel_q[i].append(int.from_bytes(frame[offset:offset + 2], byteorder='little', signed=True))

        # Convert everything to complex
        channel_complex = [
            [complex(i, q) for i, q in zip(channel_i, channel_q)]
            for channel_i, channel_q in zip(channel_i, channel_q)
        ]

        # Reshape to cube: Samples x Chirps x Channels
        cube = np.empty((128, 64, 4), dtype=complex)
        for i in range(0, 4):
            cube[:, :, i] = np.reshape(channel_complex[i], (64, 128)).T

        return cube

    def decode_radc_3d(self, frame):
        if len(frame) != 196608:
            return None

        channel_i = [[], [], [], [], [], [], [], [], [], [], [], []]
        channel_q = [[], [], [], [], [], [], [], [], [], [], [], []]

        # Split to individual I/Q channels
        for sweep in range(0, 32):
            for i in range(0, 12):
                for size in range(i*512+2, i*512+513, 4):
                    offset = sweep * 2048 + size
                    channel_i[i].append(int.from_bytes(frame[offset:offset + 2], byteorder='little', signed=True))
            for i in range(0, 12):
                for size in range(i*512, i*512+511, 4):
                    offset = sweep * 2048 + size
                    channel_q[i].append(int.from_bytes(frame[offset:offset + 2], byteorder='little', signed=True))

        # Convert everything to complex
        channel_complex = [
            [complex(i, q) for i, q in zip(channel_i, channel_q)]
            for channel_i, channel_q in zip(channel_i, channel_q)
        ]

        # Reshape to cube: Samples x Chirps x Channels
        cube = np.empty((128, 32, 12), dtype=complex)
        for i in range(0, 12):
            cube[:, :, i] = np.reshape(channel_complex[i], (32, 128)).T

        return cube


VMD3_SETTING = [
    {
        'setting_number': 1,
        'max_range': 6,             # m
        'max_speed': 10,            # km/h
        'num_samples': 128,
        'num_chirps': 64,
        'angle_setting': '2D',
        'frame_rate': 130,          # ms
        'range_resolution': 4.69,   # cm
        'speed_resolution': 0.31,   # km/h
    },
    {
        'setting_number': 2,
        'max_range': 10,             # m
        'max_speed': 10,            # km/h
        'num_samples': 128,
        'num_chirps': 64,
        'angle_setting': '2D',
        'frame_rate': 130,          # ms
        'range_resolution': 7.82,   # cm
        'speed_resolution': 0.31,   # km/h
    },
    {
        'setting_number': 3,
        'max_range': 30,            # m
        'max_speed': 30,            # km/h
        'num_samples': 128,
        'num_chirps': 64,
        'angle_setting': '2D',
        'frame_rate': 130,          # ms
        'range_resolution': 23.43,  # cm
        'speed_resolution': 0.94,   # km/h
    },
    {
        'setting_number': 4,
        'max_range': 30,            # m
        'max_speed': 50,            # km/h
        'num_samples': 128,
        'num_chirps': 64,
        'angle_setting': '2D',
        'frame_rate': 130,          # ms
        'range_resolution': 23.43,  # cm
        'speed_resolution': 1.56,   # km/h
    },
    {
        'setting_number': 5,
        'max_range': 50,            # m
        'max_speed': 50,            # km/h
        'num_samples': 128,
        'num_chirps': 64,
        'angle_setting': '2D',
        'frame_rate': 130,          # ms
        'range_resolution': 39.12,  # cm
        'speed_resolution': 1.56,   # km/h
    },
    {
        'setting_number': 6,
        'max_range': 100,            # m
        'max_speed': 100,            # km/h
        'num_samples': 128,
        'num_chirps': 64,
        'angle_setting': '2D',
        'frame_rate': 130,          # ms
        'range_resolution': 78.18,  # cm
        'speed_resolution': 3.14,   # km/h
    },
    {
        'setting_number': 7,
        'max_range': 6,             # m
        'max_speed': 10,            # km/h
        'num_samples': 128,
        'num_chirps': 32,
        'angle_setting': '3D',
        'frame_rate': 130,          # ms
        'range_resolution': 4.69,   # cm
        'speed_resolution': 0.63,   # km/h
    },
    {
        'setting_number': 8,
        'max_range': 10,            # m
        'max_speed': 10,            # km/h
        'num_samples': 128,
        'num_chirps': 32,
        'angle_setting': '3D',
        'frame_rate': 130,          # ms
        'range_resolution': 7.82,   # cm
        'speed_resolution': 0.63,   # km/h
    },
    {
        'setting_number': 9,
        'max_range': 30,            # m
        'max_speed': 30,            # km/h
        'num_samples': 128,
        'num_chirps': 32,
        'angle_setting': '3D',
        'frame_rate': 130,          # ms
        'range_resolution': 23.41,  # cm
        'speed_resolution': 1.88,   # km/h
    },
]
