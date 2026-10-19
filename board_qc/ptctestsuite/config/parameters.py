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