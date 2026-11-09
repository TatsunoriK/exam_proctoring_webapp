import io
import unittest
from starlette.requests import Request
from app.examflow_api import video_response


class StoredVideo(io.BytesIO):
    metadata = {"content_type": "video/webm"}
    length = 10


class VideoRangesTest(unittest.TestCase):
    def response(self, byte_range=None):
        headers = [(b"range", byte_range.encode())] if byte_range else []
        stream = StoredVideo(b"0123456789")
        response = video_response(stream, Request({"type": "http", "headers": headers}))
        self.assertTrue(stream.closed)
        self.assertEqual(response.headers["accept-ranges"], "bytes")
        return response

    def test_full_clip(self):
        response = self.response()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"0123456789")

    def test_seek_ranges(self):
        for requested, body, content_range in [
            ("bytes=3-5", b"345", "bytes 3-5/10"),
            ("bytes=7-", b"789", "bytes 7-9/10"),
            ("bytes=-4", b"6789", "bytes 6-9/10"),
            ("bytes=8-99", b"89", "bytes 8-9/10"),
        ]:
            with self.subTest(requested=requested):
                response = self.response(requested)
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.body, body)
                self.assertEqual(response.headers["content-range"], content_range)

    def test_invalid_ranges(self):
        for requested in ["bytes=10-", "bytes=5-2", "bytes=-0", "bytes=-", "bytes=0-1,4-5"]:
            with self.subTest(requested=requested):
                response = self.response(requested)
                self.assertEqual(response.status_code, 416)
                self.assertEqual(response.headers["content-range"], "bytes */10")
