# dict of pretty print test names

test_pretty_names = {
    "eeprom": "EEPROM",
    "temperature_test": "Temperature",
    "gbe_test": "GBe",
    "gbe_throughput_test": "GBe Throughput",
    "dummy_test": "Dummy",
    "dummy_client": "Dummy Client",
    "qc_iv_sensors_test": "QC Board IV Sensors",
    "iv_sensors_test": "IV Sensors"
}

# Section numbers in the messages refer to PTC_QC_Procedures_v1.0

def man_test(name: str, message: str, accepts_val: bool = False, limits: tuple[float, float] | None = None, unit: str | None = None):
    """Describes a manual test prompt.

    Args:
        name (str): key the result is stored under
        message (str): prompt shown to the tester
        accepts_val (bool, optional): ask the tester for a reading. Defaults to False.
        limits (tuple[float, float], optional): inclusive (min, max) acceptance range for the reading.
            When given, PASS/FAIL is decided from the reading instead of asking the tester.
        unit (str, optional): unit of the reading, shown in the prompt and stored with the value.
    """
    return {"test_name": name, "test_message": message, "accepts_value": accepts_val or limits is not None,
            "limits": limits, "unit": unit}

# these all get repeated so let's write a function to generate them, in case we
# have to change anything
def ripple_test(num: int):
    return man_test(f'ripple{num}', f'[4.3.1] Set SWT1 to position {num + 1} only. RIPPLE_{num} voltage on the DVM',
                    limits=(12.00, 12.35), unit='V')

def ripple_switch_freq(num: int):
    return man_test(f'ripple{num}_switch_period', f"[4.3.1] RIPPLE_{num} switching period on the scope (AC, 20mV, 2us)",
                    limits=(1.0, 1.1), unit='us')

def wib_led(num: int):
    return man_test(f'wib{num}_led', f"[4.3.1] Is the WIB {num} front panel LED on?")

def ripple_full_load(num: int):
    return man_test(f'ripple{num}_full_load', f"[4.4.1] RIPPLE_{num} AC ripple at full load on the scope (AC, 200mV, 200ns), peak",
                    limits=(0, 200), unit='mV')

# 4.3 Manual QC tests, PTC on the QC board without the SoM installed
pre_som_tests = [
    man_test("bare_power", "[4.3] 48V supply current with no SoM installed", limits=(0, 100), unit='mA'),
    man_test("vp12_local", "[4.3] VP12_LOCAL test point voltage on the DVM", limits=(12.00, 12.35), unit='V'),
    man_test("local_led_12v", "[4.3] Is the 12V LOCAL front panel LED on?"),
]
for _n in range(6):
    pre_som_tests += [ripple_test(_n), ripple_switch_freq(_n), wib_led(_n)]

# 4.3.2 SoM tests, after the SoM is installed and the DUT is back on the QC board
som_boot_tests = [
    man_test("som_insertion", "[4.3.2] Did the Enclustra SoM insert without excess force, with correct keying?"),
    man_test("boot_current", "[4.3.2] 48V supply current a few seconds after power on (expect about 100-200mA)", True, unit='mA'),
    man_test("amber_led_blinking", "[4.3.2] Is the amber LED on the Enclustra board blinking?"),
    man_test("12v_local_led_boot", "[4.3.2] Is the 12V LOCAL front panel LED on?"),
    man_test("pg_led_boot", "[4.3.2] Is the PG front panel LED on?"),
    man_test("fpga_done_led_boot", "[4.3.2] Is the FPGA DONE front panel LED on?"),
    man_test("serial_connection", "[4.3.2] Can you log in as root on the PTC serial port (115200 8N1)?"),
    man_test("repeat_boots", "[4.3.2] Run 'init 0', power off 60s, power on. Repeat 5 times. How many boots succeeded?",
             limits=(5, 5), unit='boots'),
]

# 4.4.2 shown right after the automated alert test
alert_led_tests = [
    man_test("over_temp_led", "[4.4.2] Did the OVER TEMP front panel LED light red during the alert test?"),
]

# 4.4.3 crate address DIP switches (SWT2)
crate_address_tests = [
    man_test(f"crate_addr_{n}", f"[4.4.3] Set SWT2 switch {n + 1} ON (others OFF). Is crate address ID {n} lit?")
    for n in range(8)
]

# 4.4.5 timing, shown after the automated timing lock test
timing_tests = [
    man_test("timing_link_led", "[4.4.5] Is the timing LINK front panel LED on?"),
    man_test("timing_rx_led", "[4.4.5] Is the RX front panel LED on?"),
    man_test("timing_rtt", "[4.4.5] Run 'dtsbutler -c local.xml mst MST_FMC align measure-delay 0'. Round trip in clock ticks (expect ~100)",
             True, unit='ticks'),
    man_test("timing_tx_led", "[4.4.5] Did the TX front panel LED light during the round trip test?"),
]

# 4.4.6 Ethernet, shown after the automated ping and throughput tests
ethernet_tests = [
    man_test("gbe_link_led", "[4.4.6] Is the GbE LINK front panel LED on?"),
    # TODO register for the AUX LED is still TBD in the procedure
    man_test("aux_led", "[4.4.6] Is the AUX front panel LED on after writing its register?"),
]

# 4.4.4 microcontroller and EtherCAT, done from the Windows machine with TwinCAT
mcu_tests = [
    man_test("mcu_program_jtag", "[4.4.4] Did programming the MCU over the XMC Link (J14) from DAVE succeed?"),
    man_test("mcu_program_insitu", "[4.4.4] Did in-situ programming with openocd (ptc-flash.cfg) succeed?"),
    man_test("ecat_link_led", "[4.4.4] Is the EtherCAT LINK front panel LED on after Toggle Free-Run?"),
    man_test("ecat_lost_frames", "[4.4.4] TwinCAT in Op mode: number of lost frames", limits=(0, 0), unit='frames'),
    man_test("ecat_debug_leds", "[4.4.4] Debug LEDs show ERR=GREEN, LINKB=GREEN, PHY LED2=BLINK GREEN?"),
    man_test("ecat_run_led", "[4.4.4] Is the ECAT RUN front panel LED on?"),
]

# 4.4.1 DC-DC load test: QC board PWM register value -> expected load current in amps
load_steps = [
    (0x216, 1.5),  # 25%
    (0x226, 3.0),  # 50%
    (0x236, 4.5),  # 75%
    (0x23e, 6.0),  # ~100%
]
load_tolerance = 0.1  # amps

# automated tests on the PTC that don't need any setup, run first
test_sequence = [
    {"test_type": "eeprom", "test_params": {}},
]

# 4.1 reception checks. These are done once per delivery, not per board, so they are
# recorded in their own shipment record instead of each board's QC record.
# The "count vs purchase order" check is built in for every shipment type.
reception_checks = {
    "front_panels": [
        man_test("fp_microscope_sample", "[4.1.1] 10% sample under the microscope: clean, no damage, thumb screws included?"),
        man_test("fp_mechanical_fit_sample", "[4.1.1] 10% sample: dimensions, mounting holes and connector openings match the drawings?"),
    ],
    "bare_pcbs": [
        man_test("bare_pcb_certificate_review", "[4.1.2] Vendor quality certificate and test reports reviewed with no problems?"),
    ],
    "assembled_pcbs": [
        man_test("assembled_pcb_certificate_review", "[4.1.3] Vendor quality certificate and test reports reviewed with no problems?"),
    ],
}

# kept for backwards compatibility with older imports
manual_tests = pre_som_tests
