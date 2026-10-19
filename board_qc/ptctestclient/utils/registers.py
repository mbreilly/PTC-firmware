# Thin wrappers around the peek/poke utilities built into the PTC image
import subprocess


def peek(addr: int) -> int:
    """Reads a 32 bit FPGA register.

    Args:
        addr (int): register address, e.g. 0x80020104

    Returns:
        int: register value
    """
    out = subprocess.run(["peek", hex(addr)], check=True, capture_output=True, text=True).stdout
    return int(out.strip().split()[-1], 16)


def poke(addr: int, value: int) -> None:
    """Writes a 32 bit FPGA register.

    Args:
        addr (int): register address, e.g. 0x80020010
        value (int): value to write
    """
    subprocess.run(["poke", hex(addr), hex(value)], check=True, capture_output=True)
