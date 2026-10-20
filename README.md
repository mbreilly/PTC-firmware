


# Power and Timing Card v4 (PTCv4) Firmware

## Maintainer

Adrian Nikolica (nikolica@hep.upenn.edu)

## Contributors

* Adrian Nikolica
* Godwin Mayers
* David Drobner

## Documentation

* [(Old) PTCv3B Design Documentation](https://docs.dunescience.org/cgi-bin/private/ShowDocument?docid=6955)
* [Warm Interface Board v3 (WIBv3) Design Documentation](https://docs.dunescience.org/cgi-bin/private/ShowDocument?docid=24127)
* [Bristol Timing Endpoint Firmware](https://gitlab.cern.ch/dune-daq/timing/dune-timing-firmware)
* [Mercury XU5 PE1 Reference Design documentation](https://github.com/enclustra/Mercury_XU5_PE1_Reference_Design)
* [Petalinux documentation](https://github.com/enclustra/PetalinuxDocumentation)
* Enclustra Application Notes
  - [I2C AppNote](https://github.com/enclustra/I2CAppNote)
  - [Gigabit Ethernet AppNote](https://github.com/enclustra/GigabitEthernetAppNote)

## Changelog
See [Changelog](changelog.md).

## Description
This respository contains firmware and software source for PTCv4. Firmware runs on an Enclustra Mercury XU5 mezzanine (ME-XU5-5EV-2I-D12E variant). Software runs on an Infineon XMC4300 EtherCAT capable microcontroller.

### Directory Structure

|      |      |
| :--- | :--- |
| Mercury_XU5_PE1/ | Contains the recreated Vivado project. Does not need to be source controlled. |
| reference_design/src/ | Verilog source files, pin/timing constraint files |
| reference_design/scripts/ | Build scripts |
| reference_design/ip_repo/ | User-generated IP |
| board_qc/ | Board QC test station: GUI and terminal app that runs PTC_QC_Procedures_v1.0 and records the results in the DUNE HWDB. See [board_qc/README.md](board_qc/README.md). |

### Board QC test station
The `board_qc/` folder has the software used to test each production PTC on the QC board and record the results in the DUNE hardware database (HWDB). It covers both production board entries (one per PTC, following PTC_QC_Procedures_v1.0) and production shipment entries (the reception checks, once per delivery). To run it:

```
cd board_qc
pip install -r ptctestsuite/requirements.txt
python -m ptctestsuite
```

This opens the test station in the browser. See [board_qc/README.md](board_qc/README.md) for the full list of steps, the HWDB setup and how to try it without hardware.

### Git instructions and building firmware
This project uses Vivado 2022.2 and petalinux 2022.2 in a Linux environment (Ubuntu 20.04.1 is used for development).

1. `git pull` changes from remote.
2. Open `vivado` from reference_design directory.
3. In tcl console, run `source ./scripts/create_project.tcl`. This recreated the project with block diagram.
4. Work on project using IDE. Build bitstream using the Vivado GUI.
5. Go to **File - Project - Write Tcl**. Set the output file to `create_project.tcl`. Check *Write all properties*, *Recreate Block Designs using Tcl*, and *Write object values*. Uncheck *Copy sources to new project*. Check the `git diff` output and ensure no files path names are corrupted before comitting changes.
6. All other HDL files should be kept in the src/ directory.
7. `git commit` all changes and `git push`.

### Building software
1. First, from Vivado: **File - Export - Export Hardware - Include Bitstream** and export to the default *Mercury_XU5_PE1/* project directory (this will export an .xsa file).
2. **File - Export - Export Hardware - Export Bitstream File** and choose the same default directory as above. Name the file *Mercury_XU5_PE1.bit*.
3. From the `reference_design/` directory on the Linux machine:`petalinux-create -t project -n ptc.linux --template zynqMP`
4. From the `petalinux/configs/` directory in this repo, copy the `config` and `rootfs_config` files to the `ptc.linux/project-spec/configs/` folder. 
5. `petalinux-config -p ptc.linux/ --get-hw-description Mercury_XU5_PE1/`. This will grab the exported .xsa and .bit files from before. In the graphical menu that pops up, select **Image Packaging Configuration - Root filesystem type - EXT4**. (This ensures the image will boot from an ext4 partition on the SD card.) This option should have been read from the `config` file copied earlier.
6. `petalinux-config -p ptc.linux/ -c rootfs` will bring up a graphical menu, and you can confirm that the choices in the `rootfs_config` file are reflected here. (There are several filesystem utilities that will be marked for install based on the file.)
7. Copy `system-user.dtsi` file in this repo to `project-spec/meta-user/recipes-bsp/device-tree/files/`. This ensures that the SD card controller, GEM (gigabit ethernet MAC that the PS uses for the SFP connection), and the I2C device on the PS, all get configured correctly.
8. From the `petalinux/recipes/` directory, copy the `regtest/` directory to `ptc.linux/project-spec/meta-user/recipes-apps/`. This adds a simple user application to the build <sup>1</sup>. Also copy `user-rootfsconfig` to `project-spec/meta-user/conf/` (this ensures that user applications are included in the root filesystem).
9. `petalinux-build -p ptc.linux` will take many tens of minutes to build the first time.
10. `petalinux-package -p ptc.linux/ --boot --u-boot --fsbl ptc.linux/images/linux/zynqmp_fsbl.elf --fpga ptc.linux/images/linux/system.bit -o ptc.linux/images/linux/BOOT.bin` will package the output into a bootable image
11. From the `ptc.linux/` directory, you can test the build by using `petalinux-boot --qemu --u-boot`. The image will boot virtually, and you can login with password `root` (change this in the config menu from step 5). You can test if simple command line utilities -- like `peek` and `i2cdetect` -- were built into the image correctly by typing them at the prompt after logging in. CTRL+A, and then X, will exit a QEMU session.

### Booting software
1. Using your favorite partition editor (e.g. `gparted`), create two partitions on an SDHC micro-SD card: a 256MB FAT32 partition named `BOOT`, and the remainder of the disk should be an EXT4 partition called `ROOT`.
2. Copy the following files from `ptc-linux/images/linux/` to the `BOOT` partition: `BOOT.bin`, `image.ub`, `boot.scr`
3. Copy the file `rootfs.tar.gz` to the `ROOT` partition. `gunzip` and then `tar -xvf` the file to uncompress the entire contents.
4. Install the SD card, and install the Enclustra XU5 module into the PTC. Ensure default jumper settings are as per schematic. Ensure a microUSB cable is attached to the front panel UART connector, and open a connection to the COM port at 115kbaud.
5. Apply 48V to the main power connector, and stop the boot when the message `Hit any key to stop autoboot` appears. This will show the `ZynqMP` prompt.
6. `setenv bootargs root=/dev/mmcblk1p2`
7. `saveenv`
8. `boot` will continue the boot process. A `ptc login:` prompt should appear.

### Starting PTC in a WEIC
1. Ensure lower nibble of SW is set to preferred backplane address (defauls is 0xF; all pulled up), and all default jumpers are installed on PTC. Connect microUSB to the front panel to a terminal emulator. Connect 1000Base-BX from SFP2 to a Bristol timing master. Connect a 1000Base-LX SFP from SFP0 to a fiber to topical converter (like 10GTek A7S2-33-1GX1GT-SFP/GT3) and then to the PC.
3. After applying 48V, it will take a few seconds for the FPGA to power. You’ll see 3 green LEDs on the front go on: 12V_LOCAL, SOC_PG, and FPGA_DONE. You may see a red OVER_TEMP LED go on at powerup, but it will turn off after the FPGA powers on. You’ll also see a blinking amber LED on the Enclustra FPGA mezzanine after a few seconds.
4. Connect to the front panel UART at 115,200 baud, 8-bit data, 1 stop bit, no parity or flow control. You may need to install the [MaxLinear XR21V1410 drivers]( https://www.maxlinear.com/product/interface/uarts/usb-uarts/xr21v1410).
5. Run the following scripts:
`python3 power_on_wib.py [wib] [on|off]`
Where `[wib]` is the slot 0 through 5 that your WIB(s) are plugged into.
`python3 setup_timing.py`
You should see a green TIMING_GOOD LED go on the PTC front panel.
`python3 start_i2c.py`
You should printouts on the PTC terminal that show the state of various sensors.

### Setting up EtherCAT
1. The EtherCAT microcontroller project is based on the [Infineon reference design](https://www.infineon.com/dgdl/Infineon-XMC4300_Relax_EtherCat_APP_Slave_SSC-GettingStarted-v04_02-EN.pdf?fileId=5546d46254e133b401554f4951cc6447). Ensure that the same version of tools are installed. Beckhoff TwinCAT3 is needed to initiate a connection to PTC. Infineon DAVE v4.1.4 or higher and the Beckhoff SSC tool v5.12 are used for creating the initial project, but is only needed for development. 
2. The first time the link is set up, or if any configuration changes, copy the `XMC_ESC.xml` file (the "ESI file") to `C:\TwinCAT\3.1\Config\Io\EtherCAT` on the host PC. 
3. Connect a 100Base-FX SFP to SFP1, with an LC-to-SC fiber connection. For bench testing, this can be connected to a optical-to-fiber converter (like the tp-link MC100CM). For DDSS connection, this will be connected to the Beckhoff EK1521 terminal. In the case of the EK1521, a second RJ-45 connection from an EK1100 to the host PC is needed.
4. Open up the TwinCAT project in the `ethercat/` directory.
5. Double click on "Device 1 (EtherCAT)" and click on the "Adapter" panel. Ensure that the correct PTC Ethernet interface is selected. 
6. Right click on Device 1, and click "Scan". A message saying "Configuration matched" should appear. 
7. Now click on the "Online" tab. PTC should appear as a "Box" and be labelled "XMC_ESC". 
8. In the top menu bar, click on the "Toggle Free-Run State" icon (a red circular arrow). 
9. Now the PTC can be changed to "Op" mode in the Online panel. There will be constant frame counters in this panel, and no lost frames. This means PTC is maintaining an EtherCAT link. On the EK1521, the "RUN" LED will be constantly illuminated. The PTC Debug LEDs will show: ERR=GREEN, LINKB=GREEN, PHY_KED2=BLINK GREEN. 

### Developing with EtherCAT
1. Open DAVE and open the project at `ethercat/xmc_4300_proj/`. This is an Eclipse-like environment where the code can be modified asnd re-built.
2. The EtherCAT block is implemented in a DAVE "App" and has minimal configuration.
3. To change the data exchange types that PTC uses, the `XMC_ESC.xlsx` Excel file definitions need to be changed using SSC OD tool.exe. See the [Beckhoff ET9300 app note](https://download.beckhoff.com/download/document/io/ethercat-development-products/an_et9300_v1i8.pdf). 
4. If the DAVE project is modified, it must be reloaded onto the XMC4300 using the [KITXMCLINKSEGGERV1TOBO1 JTAG pod](https://www.digikey.com/en/products/detail/infineon-technologies/KITXMCLINKSEGGERV1TOBO1/5970448?s=N4IgTCBcDaIB4FsDGACANgSwHYGsQF0BfIA) connected to J6 on the PTC. (There is a provision to reprogram from the FPGA, but this is not implemented at the time of this writing). This only needs to be done once, and successive power-ups will retian the programming. To program the XMC4300 without using DAVE, the [J-Flash Lite](https://www.segger.com/downloads/jlink/) utility will still need to be used with the Infineon programming pod. The `.hex` file generated in `ethercat/xmc_proj/Debug` is used.
5. A preliminary data exchange test exists. To run it, use `python3 ecat_test1.py`, which will send one temperature reading and the 48V line current across the EtherCAT link. The IN_GENERIC_INT values in TwinCAT will show: TMP117 ADC counts, LTC2945 ADC counts, an alignment word (0xcafe), and a sequence number 0-65535 that updates once per second with the ADC reads and rolls over. Provision to exhange further data between the FPGA an XMC4300 is pending.

### To set up a permanent IP address:
1. Change the `setup_timing.py` script to use your IP address of choice.
2. Create a script `/etc/init.d/start_network.sh` with the following lines, which will run the above script to enable the Zynq GbE controller <sup>2</sup>and eth1 interface (and enable the timing interface):

`#!/bin/sh`

`python3 /home/root/setup_timing.py`

3. Make the script executable with `chmod +x`.
4. Issue the following commands to make symbolic links to this script in the appropriate startup directories, which will run the script at bootup:

`ln -s /etc/init.d/start_network.sh /etc/rc2.d/S99start_network.sh`

`ln -s /etc/init.d/start_network.sh /etc/rc3.d/S99start_network.sh`

`ln -s /etc/init.d/start_network.sh /etc/rc4.d/S99start_network.sh`

`ln -s /etc/init.d/start_network.sh /etc/rc5.d/S99start_network.sh`

5. Test by powering down PTC with `init 0` and turning off the main 48V supply, waiting a minute for the supply capacitors to discharge, and then powering on again. The PTC should show eth1 up and running with the IP address chosen in step 1. 

### To transfer files to and from PTC:
1. From host to PTC (from host): `rsync -avzh [file to transfer] root@[your IP address]:/home/root/`
2. From PTC to host (from host): `rsync -avzh root@[your IP address]:/home/root/[file to transfer] .`

### Register reads and writes
At the root prompt, registers can be manually written using `poke [addr] [data]` from the table below. For example `poke 0x43c00000 0x00000020` will assert opad\_EXT\_RST. Test scripts (below) initiate sequences of register writes.

1. Control registers (R/W). All register bit defaults are low at powerup.

| reg. no. | AXI addr. | bit(s) | name | description |
| ------ | ------ | ------ | ------ | ------ |
| 0 | 0x80020000 | [0] | SOC_I2C_SW_RST | Reset 4-port I2C switch UT16 between SoC PS I2C, and PWR_SENSE and 3 SFPs. Active low (i.e. power-up in reset). |
| 0 | 0x80020000 | [8] | MCU_I2C_OE | Enable outputs on I2C level translator UT25 to route WIB I2C to MCU instead of SoC. NOTE: needs resistor change in HW to work. |
| 0 | 0x80020000 | [9] | WIB_I2C_OE | Enable outputs on I2C level translator UT29 to route WIB I2C to SoC. |
| 0 | 0x80020000 | [16] | bp_io_oe | Tri-state buffer enable to BP_IO_EN (active low) on level translator UT36, from WIB priority encode into SoC. Reg bit inverse to "T" buffer input. Reg low -> tri-state hi-Z -> OE on-board pullup -> no input to SoC. Reg high -> drive OE low -> can read lines from SoC. Low is used in conjunction with wib_rx_sel_out and wib_pe_soc_en when overriding priority encoder.  |
| 0 | 0x80020000 | [23] | crate_addr_en | Tri-state buffer enable to CRATE_ADDR_OE (active low) on level translator UB1, from backplane into SoC. Reg bit inverse to "T" buffer input. Reg low -> tri-state hi-Z -> OE on-board pullup -> no input to SoC. Reg high -> drive OE low -> can read lines from SoC. |
| 0 | 0x80020000 | [24] | crate_addr_out |  Deprecated. (To drive crate address out to WIB. Would have required HW change on level translator direction pin.) |
| - | - | - | - | - |
| 1 | 0x80020004 | [2:0] | wib_rx_sel_out | Use to drive clock MUX UT30 to select which WIB timing TX to route to SFP. Used in conjunction with wib_pe_soc_en and bp_io_en when overriding priority encoder. |
| 1 | 0x80020004 | [3] | wib_pe_soc_en | Tri-state buffer enable to level translator UT38, from priority encoder into clock MUX. Reg bit inverse to "T" buffer input. Reg low -> OE on-board pullup thru FET -> priority encoder output to clock MUX. Reg high -> OE pulled low thru FET -> can drive WIB_RX_SEL from FPGA. High is used in conjunction with wib_rx_sel_out and bp_io_en when overriding priority encoder. |
| 1 | 0x80020004 | [8] | sfp2_tx_en_reg | High = timing SFP JT5 force transmit (SFP_TX_DISABLE = low). For test only. |
| 1 | 0x80020004 | [9] | sfp2_tx_mux_ovr | High = timing SFP JT5 will transmit if any of BP_IO[5:0] driven from SoC are low. For test only. |
| 1 | 0x80020004 | [10] | ep_srst | Resets the timing endpoint firmware block. |
| 1 | 0x80020004 | [11] | ep_clk_sel | Switch BUFGMUX clk output in endpoint wrapper. Low = clk, high = rec_clk (bypass endpoint). Not currently used, as endpoint is for status indicator only. |
| 1 | 0x80020004 | [16] | WIB_CLK_SEL | Controls input of clock fanout UT37. Low = SFP RX gets fanned out to WIBs. High = SOC_AUX_CLK (internally generated). |
| 1 | 0x80020004 | [17] | mmcm_rst_n | Reset MMCM for SOC_AUX_CLK. Power-up: hold in reset. For test only. |
| - | - | - | - | - |
| 2 | 0x80020008 | [0] | EN_3V3 | Enable local 3.3V converter. Reg bit inverted. Power-up: OFF. |
| - | - | - | - | - |
| 3 | 0x8002000c | [0] | EN_2V5 | Enable local 2.5V converter. Reg bit inverted. Power-up: OFF. |
| - | - | - | - | - |
| 4 | 0x80020010 | [0] | VP12_EN0 | Enable WIB 0 power. Power-up: OFF. |
| - | - | - | - | - |
| 5 | 0x80020014 | [0] | VP12_EN1 | Enable WIB 1 power. Power-up: OFF. |
| - | - | - | - | - |
| 6 | 0x80020018 | [0] | VP12_EN2 | Enable WIB 2 power. Power-up: OFF. |
| - | - | - | - | - |
| 7 | 0x8002001c | [0] | VP12_EN3 | Enable WIB 3 power. Power-up: OFF. |
| - | - | - | - | - |
| 8 | 0x80020020 | [0] | VP12_EN4 | Enable WIB 4 power. Power-up: OFF. |
| - | - | - | - | - |
| 9 | 0x80020024 | [0] | VP12_EN5 | Enable WIB 5 power. Power-up: OFF. |
| - | - | - | - | - |
| 10 | 0x80020028 | [6:0] | vp12_sync_en[6:0] | Deprecated. (SYNC pin on all seven 12V converters. Requires resistor change in HW to work.) |
| - | - | - | - | - |
| 10 | 0x80020028 | [7] | lvsync_en | Deprecated. (SYNC pin on local 3.3V/2.5V converter. Requires resistor change in HW to work.)|
| - | - | - | - | - |
| 11 | 0x8002002c | [0] | xmc_jtag_en | Bit inverted. Low = all four buffers to control MCU JTAG interface are tri-stated so programming pod can be used. High = controlled by firmware. |
| 11 | 0x8002002c | [4] | cpu_tms_out | Assert TMS. |
| 11 | 0x8002002c | [5] | cpu_tck_out | Assert TCK. |
| 11 | 0x8002002c | [6] | xmc_tdi_n | Assert TDI. |
| 11 | 0x8002002c | [8] | xmc_reset_en | Active low reset to MCU. |
| - | - | - | - | - |
| 12 | 0x80020030 | [0] | SFP0_SPARE_LED | To be used as GbE link status controlled by SW. |
| 12 | 0x80020030 | [1] | OVER_TEMP_LED | To be used as OR of all temp sensor alerts controlled by FPGA. |

2. Status registers (R/O). 

| reg. no. | AXI addr. | bit(s) | name | description |
| ------ | ------ | ------ | ------ | ------ |
| 64 | 0x80020100 | [0] | SFP0_TX_FAULT | low = okay, high = fault detected |
| 64 | 0x80020100 | [1] | SFP0_LOS | low = signal present, high = loss of signal |
| 64 | 0x80020100 | [2] | SFP0_PRESENT | low = present, high = not present |
| 64 | 0x80020100 | [8] | SFP1_TX_FAULT | low = okay, high = fault detected |
| 64 | 0x80020100 | [9] | SFP1_LOS | low = signal present, high = loss of signal |
| 64 | 0x80020100 | [10] | SFP1_PRESENT | low = present, high = not present |
| 64 | 0x80020100 | [16] | SFP2_TX_FAULT | low = okay, high = fault detected |
| 64 | 0x80020100 | [17] | SFP2_LOS | low = signal present, high = loss of signal |
| 64 | 0x80020100 | [18] | SFP2_PRESENT | low = present, high = not present |
| - | - | - | - | - |
| 65 | 0x80020104 | [13:8] | BP_IO | Current status of priority encode lines from WIBs |
| 65 | 0x80020104 | [18:16] | wib_rx_sel_in | Current status of priority encode lines from WIBs |
| 65 | 0x80020104 | [27:24] | timing_stat | 4-bit status code from timing endpoint -- see Timing Integration document |
| 65 | 0x80020104 | [28] | timing_lock | Timing status LED (high when timing_stat = 0x8) |
| - | - | - | - | - |
| 66 | 0x80020108 | [6:0] | VP_12_IV_ALERT | Low = alert. Bit [6] is local DC-DC converter, and bits [5:0] are WIBs 5-->0 respectively. |
| 66 | 0x80020108 | [8] | VP2V5_ALERT | Low = alert. Local 2.5V DC-DC converter. |
| 66 | 0x80020108 | [9] | VP3V3_ALERT | Low = alert. Local 2.5V DC-DC converter. |
| 66 | 0x80020108 | [18:16] | OVER_TEMP | Low = alert. OR of temp sensor alerts. Bit [16] is OR of TU28, UT8, UT9, UT12. Bit [17] is OR of UT20, UT19, UT31, UT32. Bit [18] is currently unassigned. |
| 66 | 0x80020108 | [24] | VP48_IV_ALERT | Low = alert. Main 48V input monitor. |
| - | - | - | - | - |
| 126 | 0x800201f8 | [0] | mmcm0_locked | Internal MMCM for "fake" timing clock -- for test only.|
| - | - | - | - | - |
| 127 | 0x800201fc | [31:0] | 0xdeadbeef | Test register|

## Footnotes
1. This is done by creating an app template as in the [PetaLinux Yocto documentation](https://xilinx-wiki.atlassian.net/wiki/spaces/A/pages/18842475/PetaLinux+Yocto+Tips#PetaLinuxYoctoTips-CreatingApps(whichuseslibraries)inPetaLinuxProject)
2. The Zynq GbE interface is on the PS side using the GEM controller. The software driver mode is defined through Petalinux using the system-user.dtsi device tree file, which sets it as `is-internal-pcspma`. For some reason, the Xilinx drivers do not automatically enable the GEM when it's in this mode, so the script writes the correct values to the [network_config](https://www.xilinx.com/htmldocs/registers/ug1087/ug1087-zynq-ultrascale-registers.html) register for GEM1. An alternate solution is to [change the driver code](https://github.com/DUNE-DAQ/dune-wib-firmware/blob/master/linux-2020.1/project-spec/meta-user/recipes-kernel/linux/linux-xlnx/macb-5.4.patch#L30) as was done on the WIB.
