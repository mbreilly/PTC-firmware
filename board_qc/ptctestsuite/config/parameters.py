ptc_ip = "192.168.20.100"
qc_ip = "192.168.20.101"
ws_port = 8765
ptc_client_path = "/home/root/ptctestclient"

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

# QC board load control (procedure 4.4.1). Converter n uses qc_load_base_addr + 4*n
qc_user = 'root'
qc_password = ''
qc_load_base_addr = 0x80020038
# written before each load value, as in the procedure (poke 0x316 then 0x2xx)
qc_load_enable_value = 0x316
# TODO confirm the value that turns the load off
qc_load_off_value = 0x0
load_settle_time = 1.0

# GbE throughput test (procedure 4.4.6.2)
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
