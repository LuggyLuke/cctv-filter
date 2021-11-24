import logging
import os
from datetime import datetime
from typing import List

import cv2
import numpy as np
from deepstack_sdk import Detection, viz
from deepstack_sdk.structs import DetectionResponse
from shapely.geometry import Polygon, box


class ReolinkVideo:
    REOLINK_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
    FRIENDLY_TIMESTAMP_FORMAT = "%Y-%m-%d %H-%M-%S"
    VALID_DETECTION_LABELS = os.environ["VALID_DETECTION_LABELS"].rsplit(", ")

    def __init__(
        self,
        path: str,
        filename: str,
        extension: str,
    ):
        self.path = path
        self.filename = filename
        self.extension = extension

        (
            self.camera_name,
            self.camera_num,
            self.timestamp,
        ) = self.split_reolink_filename(filename)

    @classmethod
    def split_reolink_filename(cls, filename: str):
        # Example: "Front Door_01_20210511082721"
        try: 
            filename_parts = filename.rsplit("_", 2)
            camera_name = filename_parts[0]
            camera_num = filename_parts[1]
            timestamp = datetime.strptime(
                filename_parts[2], cls.REOLINK_TIMESTAMP_FORMAT
            )
        except:
            camera_name = os.environ["CAMERA_1"]
            camera_num = "01"
            timestamp = datetime.strptime(
                "20000101010000", cls.REOLINK_TIMESTAMP_FORMAT
            )
            logging.info("Filename format not as expected, returning generic format")
            
        return camera_name, camera_num, timestamp      

    @property
    def friendly_timestamp(self):
        return self.timestamp.strftime(self.FRIENDLY_TIMESTAMP_FORMAT)

    @property
    def filename_with_ext(self):
        return f"{self.filename}.{self.extension}"

    @property
    def full_path(self):
        return os.path.join(self.path, self.filename_with_ext)

    def friendly_filename(self, extension: str = None):
        if extension is None:
            extension = self.extension
        return f"{self.friendly_timestamp} ({self.camera_name}).{extension}"

    def _frame_to_bytes(self, frame):
        success, im_buffer = cv2.imencode(".jpg", frame)
        if not success:
            raise Exception("Failed to convert numpy array to image.")
        return im_buffer.tobytes()

    def _detection_in_roi(self, detection, roi):
        object = box(
            detection.x_min,
            detection.y_min,
            detection.x_max,
            detection.y_max,
        )
        return object.intersects(roi)

    def _is_accepted_detection(self, detection, roi=None):
        if detection.label not in self.VALID_DETECTION_LABELS:
            return False
        if roi is None:
            return True
        else:
            return self._detection_in_roi(detection, roi)

    def _draw_roi(self, frame, roi):
        roi_array = np.array(roi.exterior.coords, np.int32)
        return cv2.polylines(frame, [roi_array], True, (255, 0, 0), 2)

    def is_accepted(
        self,
        deepstack: Detection,
        min_confidence: float = 0.5,
        roi: Polygon = None,
    ):
        logging.info(f"ANALYSING {self.filename_with_ext}")
        video = cv2.VideoCapture(
            os.path.join(self.path, self.filename_with_ext)
        )
        current_frame = target_frame = 1
        read_ok, frame = video.read()
        if not read_ok:
            logging.error(f"Unable to read {self.filename_with_ext}")

        while read_ok is True:
            if current_frame == target_frame:
                response = deepstack.detectObject(
                    self._frame_to_bytes(frame), min_confidence=min_confidence
                )
                for detection in response.detections:
                    if self._is_accepted_detection(detection, roi):
                        logging.info(
                            ", ".join(
                                [
                                    f"ACCEPTED {self.filename_with_ext}",
                                    f"{detection.label} detected ({100 * detection.confidence}%)",
                                ]
                            )
                        )
                        video.release()
                        return True, frame, response
                target_frame += 15  # Skip 15 frames (roughly 0.5s)
            read_ok, frame = video.read()
            current_frame += 1

        logging.info(f"REJECTED {self.filename_with_ext}")
        video.release()
        return False, None, None

    def move(self, target_path: str):
        target_full_path = os.path.join(target_path, self.friendly_filename())
        os.rename(self.full_path, target_full_path)

    def save_images_from_frame(
        self,
        frame: np.ndarray,
        deepstack_response: DetectionResponse,
        outputs: List[str],
        draw_roi=False,
        roi=None,
    ):
        frame = viz.drawResponse(frame, deepstack_response)
        if draw_roi is True and roi is not None:
            frame = self._draw_roi(frame, roi)
        for output in outputs:
            cv2.imwrite(output, frame)
