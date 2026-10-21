# ptc_ip is discovered at runtime (DHCP on end1) and passed explicitly to the
# functions that need it, so it is left as a placeholder here.
ptc_ip = None
qc_ip = "192.168.20.101"
ws_port = 8765

# HWDB
ptc_part_type_id = "D08104300001"
ptc_qc_test_id = 880
bearer_token_path = "/run/user/1000/bt_u1000"
dune_hwdb_api_path = "https://dbwebapi2.fnal.gov:8443/cdbdev/api/v1" 
local_cache_file = "tested_boards"
token_renewal_interval = 3600

# Image Capture
webcam_id = 0
image_capture_width = 1280
image_capture_height = 720
image_crop_width = 1080
image_crop_height = 720

# ptc authentication settings
# NOTE: if this ever becomes important, read this from environment variables
ptc_user = 'root'
ptc_password = 'root'

# QC board load control (procedure 4.4.1). Since procedures v1.4 the registers run backwards:
# converter 0 is 0x8002004c and converter 5 is 0x80020038, so converter n uses qc_load_conv0_addr - 4*n
qc_user = 'root'
qc_password = ''
qc_load_conv0_addr = 0x8002004c
# written before each load value, as in the procedure (poke 0x316 then 0x2xx)
qc_load_enable_value = 0x316
# TODO confirm the value that turns the load off
qc_load_off_value = 0x0
load_settle_time = 1.0

# QC board timing endpoint lock (procedure 4.5.4, channel 0 only for now)
qc_timing_ctrl_addr = 0x80020004
qc_timing_status_addr = 0x80020104
qc_timing_locked_value = 0x18000000

# GbE throughput test (procedure 4.5.5.2)
throughput_test_mb = 1000
throughput_min_mb_s = 12.5

# Shipment reception checks (procedure 4.1), recorded once per delivery
reception_log_file = "reception_records.jsonl"
# Each shipment gets its own entry in the same HWDB as the boards, with serial
# number reception_serial_prefix + PO number, and the checks are attached to it.
# TODO a dedicated shipment part type would keep these out of the PTC board list
reception_part_type_id = ptc_part_type_id
reception_serial_prefix = "SHIPMENT-"

# Results that failed to upload to the HWDB are kept here, one JSON record per line
unuploaded_results_file = "unuploaded_results.jsonl"

# GUI (python -m ptctestsuite). The GUI is a local web page served on this port.
gui_port = 8080
gui_title = "PTC QC Test Station"
gui_station = "Penn, bench 1"

# Board photos (procedure 4.1.3): the front and back of every board, uploaded to the HWDB.
# A copy of every photo is also kept in photo_dir on this computer.
photo_dir = "board_photos"
# Alignment guides shown over the camera view, one per side. Set from the GUI.
ghost_image_dir = "ghost_images"
photo_max_mb = 20
# The browser asks the camera for this resolution and gets the closest it supports
camera_width = 3840
camera_height = 2160

# This station's record of every board it tested, one JSON file per serial. Used for the
# lookup lists, as a fallback when the HWDB can't be reached, and to spot a SoM or EEPROM
# seen on two boards. The HWDB stays the master copy.
board_records_dir = "board_records"
# HWDB test type for repair records. It must exist on the PTC component type in the HWDB.
repair_test_type = "Repair"
qc_test_type = "QC Test"
max_repair_photos = 6
