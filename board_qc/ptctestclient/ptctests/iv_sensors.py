"""Test script that runs on the PTC to read the IV sensors
located on the QC board for voltage and current monitoring.
"""

import subprocess
from dataclasses import dataclass
from subprocess import CalledProcessError
from time import sleep
from loguru import logger as lg

from ptctestclient.utils import test_base, qc_result


@dataclass
class IVSensorChannel:  # pylint: disable=too-many-instance-attributes
    """A single IV sensor channel on the QC board."""

    sensor_addr: str
    v_min: float
    v_max: float
    i_min: float
    i_max: float
    resistor: float
    voltage: float | None = 0.0
    current: float | None = 0.0


class iv_sensors_test(test_base):  # pylint: disable=invalid-name
    """Test script that runs on the PTC to read the IV sensors
    located on the QC board for voltage and current monitoring.
    """

    def __init__(self):
        self.channels = []
        self.sleep_time = 0.1
        super().__init__()

    def test_init(self) -> bool:
        """Initialize the sensor addresses and respective ranges
        with exceptions for aux and SoM sensors.

        Returns:
            bool: successful initialization
        """
        lg.info("Starting voltage and current sensor test...")

        self.channels = [
            # Main sensors (12V rail, 0.005 ohm sense resistor)
            # current limits are 1.5A +/- 100mA at 25% load (procedure 4.5.1.2)
            IVSensorChannel("0x67", 12.0, 12.35, 1.4, 1.6, 0.005),
            IVSensorChannel("0x68", 12.0, 12.35, 1.4, 1.6, 0.005),
            IVSensorChannel("0x69", 12.0, 12.35, 1.4, 1.6, 0.005),
            IVSensorChannel("0x6a", 12.0, 12.35, 1.4, 1.6, 0.005),
            IVSensorChannel("0x6b", 12.0, 12.35, 1.4, 1.6, 0.005),
            IVSensorChannel("0x6c", 12.0, 12.35, 1.4, 1.6, 0.005),
            # SoM sensor (<= 2A, procedure 4.5.1.3)
            IVSensorChannel("0x6d", 12.0, 12.35, 0.0, 2.0, 0.005),
            # Aux sensors (2.5V and 3.3V rails, 0.02 ohm sense resistor, <= 2A, procedure 4.5.1.4)
            IVSensorChannel("0x6e", 2.4, 2.6, 0.0, 2.0, 0.02),
            IVSensorChannel("0x6f", 3.2, 3.4, 0.0, 2.0, 0.02),
        ]

        self.sleep_time = 0.1
        return True

    def read_voltage(self, addr: str) -> float | None:
        """Reads I2C voltage bits from the IV sensor,
        parses into decimal, and calculates voltage.

        Args:
            addr (str): hex address of the IV sensor

        Returns:
            voltage (float | None): voltage reading in volts, or None on failure
        """
        voltage_lsb = 0.025

        try:
            i2c_raw_cmd = subprocess.run(
                ["i2cget", "-y", "0", str(addr), "0x1e", "w"],
                check=True,
                capture_output=True,
                text=True,
            )
            i2c_raw = i2c_raw_cmd.stdout
            i2c_dec = ((int(i2c_raw[4:6], 16) << 8) + int(i2c_raw[2:4], 16)) >> 4
            voltage = i2c_dec * voltage_lsb
            return voltage
        except CalledProcessError as e:
            lg.error(f"Voltage reading failed for sensor {addr}")
            lg.exception(e)
            return None
        except ValueError as e:
            lg.error(f"Invalid voltage reading from sensor {addr}")
            lg.exception(e)
            return None

    def read_current(self, addr: str, resistor: float) -> float | None:
        """Reads I2C current bits from the IV sensor,
        parses into decimal, and calculates current.

        Args:
            addr (str): hex address of the IV sensor
            resistor (float): resistance value for current calculation

        Returns:
            current (float | None): current reading in amps, or None on failure
        """
        sense_voltage_lsb = 0.000025

        try:
            i2c_raw_cmd = subprocess.run(
                ["i2cget", "-y", "0", str(addr), "0x14", "w"],
                check=True,
                capture_output=True,
                text=True,
            )
            i2c_raw = i2c_raw_cmd.stdout
            i2c_dec = ((int(i2c_raw[4:6], 16) << 8) + int(i2c_raw[2:4], 16)) >> 4
            current = i2c_dec * sense_voltage_lsb / resistor
            return current
        except CalledProcessError as e:
            lg.error(f"Current reading failed for sensor {addr}")
            lg.exception(e)
            return None
        except ValueError as e:
            lg.error(f"Invalid current reading from sensor {addr}")
            lg.exception(e)
            return None

    def run_test(self) -> qc_result:
        """Iterates through the IV sensors,
        reads voltage and current, and evaluates if they are
        within the acceptable range.

        Returns:
            qc_result: pass or fail based on the readings/ranges
        """
        mux_addr = "0x70"
        aux_mux_channel = 0x04
        main_mux_channel = 0x08

        for ch in self.channels:
            try:
                # select the mux channel first so voltage and current come from the same bus
                if ch.sensor_addr in ["0x6e", "0x6f"]:
                    subprocess.run(
                        ["i2cset", "-y", "-r", "0", mux_addr, hex(aux_mux_channel)],
                        check=True,
                    )
                    sleep(1)
                else:
                    subprocess.run(
                        ["i2cset", "-y", "-r", "0", mux_addr, hex(main_mux_channel)],
                        check=True,
                    )
                    sleep(1)

                ch.voltage = self.read_voltage(ch.sensor_addr)
                ch.current = self.read_current(ch.sensor_addr, ch.resistor)
                sleep(self.sleep_time)

            # A catch-all exception is acceptable here, as we are looking for any
            # sort of failure.
            except Exception as e:  # pylint: disable=broad-exception-caught
                # The previous functions will return more detailed errors,
                # making this error test-specific.
                lg.critical(
                    f"Reading sensor {ch.sensor_addr} was unsuccessful!"
                    " Marking test as failed"
                )
                lg.exception(e)
                ch.voltage = None
                ch.current = None

        # check every channel so all readings get recorded, even after a failure
        result = qc_result.PASS
        for ch in self.channels:
            self.values[f"{ch.sensor_addr}_voltage"] = None if ch.voltage is None else round(ch.voltage, 3)
            self.values[f"{ch.sensor_addr}_current"] = None if ch.current is None else round(ch.current, 3)

            if ch.voltage is None or ch.current is None:
                lg.error(f"Null reading on sensor {ch.sensor_addr}")
                result = qc_result.FAIL
                continue

            if ch.voltage < ch.v_min or ch.voltage > ch.v_max:
                lg.error(f"Voltage out of range on {ch.sensor_addr}: {ch.voltage}V")
                result = qc_result.FAIL

            if ch.current < ch.i_min or ch.current > ch.i_max:
                lg.error(f"Current out of range on {ch.sensor_addr}: {ch.current}A")
                result = qc_result.FAIL

        if result == qc_result.PASS:
            lg.info("Voltage and current monitoring test passed.")
        return result
