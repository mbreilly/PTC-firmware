import asyncio
import cv2

import io

from ptctestsuite.config.parameters import webcam_id, image_capture_width, image_capture_height, image_crop_width, image_crop_height
from loguru import logger as lg

def image_proc():
    cap = cv2.VideoCapture(webcam_id)
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, image_capture_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, image_capture_height)

    hor_diff = int((image_capture_width - image_crop_width) / 2)
    vert_diff = int((image_capture_height - image_crop_height)/2)

    while True:
        ret, frame = cap.read()
        """
        if not ret:
            print("Failed to show image!")
            break
        """

        key = cv2.waitKey(1) & 0xFF

        frame = frame[
            vert_diff:vert_diff + image_crop_height,
            hor_diff:hor_diff + image_crop_width
        ]

        cv2.imshow("Camera", frame)

        if key == 27:
            break
        elif key == 32:
            cap.release()
            cv2.destroyAllWindows()
            # frame_crop = frame[hor_diff:image_capture_width-hor_diff, vert_diff:image_capture_width-vert_diff]
            #return frame_crop
            return frame


async def get_board_image():
    loop = asyncio.get_event_loop()

    #ret, frame = await loop.run_in_executor(None, cap.read)
    frame = await loop.run_in_executor(None, image_proc)

    success, encoded_image = cv2.imencode('.png', frame)

    if success:
        return io.BytesIO(encoded_image.tobytes()).read()
    else:
        lg.critical("Failed to capture board image!")
        return

