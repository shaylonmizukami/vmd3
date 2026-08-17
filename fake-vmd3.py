import socket
import struct
import threading
import time

import numpy as np

HOST = '0.0.0.0'
PORT = 6172

UDP_TARGET = ('127.0.0.1', 4567)
FRAME_INTERVAL = 0.131
PAYLOAD_SIZE = 131072
CHUNK = 1500

streaming = threading.Event()

def ack(header, status=0):
    return header + struct.pack('<I', 1) + bytes([status])


def make_frame(counter):
    n = PAYLOAD_SIZE // 2
    t = np.arange(n)
    wave = 2000 * np.sin(2 * np.pi * (t + counter * 137) / 512.0)
    payload = wave.astype('<i2').tobytes()
    return b'RADC' + struct.pack('<I', PAYLOAD_SIZE) + payload


def udp_sender():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    counter = 0
    print('[FAKE] UDP sender armed')
    while True:
        streaming.wait()
        frame = make_frame(counter)
        for i in range(0, len(frame), CHUNK):
            sock.sendto(frame[i:i + CHUNK], UDP_TARGET)
        counter += 1
        if counter % 10 == 0:
            print(f'[FAKE] sent {counter} frames')
        time.sleep(FRAME_INTERVAL)


def main():
    threading.Thread(target=udp_sender, daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    print(f'[FAKE] Control server listening on {HOST}:{PORT}')

    while True:
        conn, addr = server.accept()
        print(f'[FAKE] Client connected from {addr}')
        try:
            while True:
                head = conn.recv(8)
                if len(head) < 8:
                    print('[FAKE] Client disconnected')
                    break

                header = head[0:4]
                length = struct.unpack('<I', head[4:8])[0]

                payload = b''
                while len(payload) < length:
                    payload += conn.recv(length - len(payload))

                if payload:
                    value = struct.unpack('<I', payload[0:4])[0]
                    print(f'[FAKE] {header.decode()} -> {value}')
                else:
                    print(f'[FAKE] {header.decode()}')

                conn.sendall(ack(header))

                if header == b'RDOT':
                    streaming.set()
                    print('[FAKE] streaming started')
                if header == b'GBYE':
                    streaming.clear()
        finally:
            conn.close()


if __name__ == '__main__':
    main()
