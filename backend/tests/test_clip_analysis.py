import io
import unittest
from unittest.mock import patch

import av
import numpy as np

from app.clip_analysis import analyze_video


class ClipAnalysisTest(unittest.TestCase):
    def test_webm_decodes_from_memory(self):
        output = io.BytesIO()
        with av.open(output, "w", format="webm") as container:
            stream = container.add_stream("libvpx", rate=5)
            stream.width = 64
            stream.height = 64
            stream.pix_fmt = "yuv420p"
            for _ in range(10):
                frame = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), dtype=np.uint8), format="rgb24")
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        with patch("app.main.extract_frame", return_value={"features": {}}), patch("app.main.predict", return_value={"prediction": "suspicious", "probabilities": {"suspicious": 0.8}}):
            result = analyze_video(output.getvalue(), ".webm")
        self.assertEqual(result["frames_analyzed"], 2)
        self.assertEqual([flag["time_s"] for flag in result["review_flags"]], [0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
