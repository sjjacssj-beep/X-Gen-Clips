import os
import subprocess
from pathlib import Path
from typing import Tuple

def compute_face_center_x(video_path: Path, sample_seconds: float = 2.0) -> float:
    """
    Computes horizontal center (0.0 to 1.0) of active speaker in video.
    Returns 0.5 (center) if no face detected or OpenCV unavailable.
    """
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_idx = int(fps * sample_seconds)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return 0.5

        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Use Haar Cascade face detector built into OpenCV
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if os.path.exists(cascade_path):
            face_cascade = cv2.CascadeClassifier(cascade_path)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            if len(faces) > 0:
                # Pick largest face
                largest_face = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest_face
                face_center_x = (fx + fw / 2.0) / float(w)
                # Keep within safe bounds [0.2, 0.8]
                return max(0.2, min(0.8, face_center_x))
    except Exception:
        pass

    return 0.5
