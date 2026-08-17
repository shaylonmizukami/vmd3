'''
pip install zaber-motion

Example Usage: python zaber.py --serial_dev=/dev/ttyUSB0 --frequency=0.5 --duration=60
'''

import argparse
import sys
import time

from zaber_motion import Units
from zaber_motion.ascii import Connection


def main(serial_dev='/dev/ttyUSB0', amplitude=5000, frequency=1, duration=60):
    connection = Connection.open_serial_port(serial_dev)
    
    try:
        deviceList = connection.detect_devices()
        print(f'Found {len(deviceList)} device(s):')
        print(deviceList)

        if len(deviceList) == 0:
            return

        zaber = deviceList[0]

        # Home Axis
        axis = zaber.get_axis(1)
        axis.home()

        # Move zaber slighty by 10 mm
        axis.move_relative(10, Units.LENGTH_MILLIMETRES)

        # Calculate the time interval and number of cycles for the specified frequency and duration
        time_ms = int((1 / frequency) * 1000)
        num_cycles = int(duration / (time_ms / 1000))

        print(f'move sin {amplitude} {time_ms} {num_cycles}')

        # Start movement cycle
        axis.generic_command(f'move sin {amplitude} {time_ms} {num_cycles}')
        time.sleep(duration)
        axis.wait_until_idle()
        print("Done!")

        # Finish, reset to home position
        axis.home()
    except Exception as e:
        print(e)

    connection.close()
    return

if __name__ == '__main__':
    # Create the parser
    parser = argparse.ArgumentParser(description="Zaber Mover")

    # Add arguments
    parser.add_argument('--serial_dev', type=str, default='/dev/ttyUSB0', help='Serial Port for the Zaber Mover (Default=/dev/ttyUSB0)')
    parser.add_argument('--amplitude', type=int, default=5000, help='Mover Amplitude in nm (Default=5000)')
    parser.add_argument('--frequency', type=float, default=1, help='Mover Frequency in Hz (Default=1Hz)')
    parser.add_argument('--duration', type=int, default=60, help='Mover Duration in Seconds (Default=60s)')

    # Parse arguments
    args = parser.parse_args()
    main(args.serial_dev, args.amplitude, args.frequency, args.duration)
