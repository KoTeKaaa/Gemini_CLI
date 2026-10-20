import unittest
from unittest.mock import Mock
from gemini_cli.protocol.images import encode_images, decode_images, validate_payload_images
from gemini_cli.protocol.attachments import ImageAttachment
from gemini_cli.backends.genai import to_gemini
from gemini_cli.backends.remote import RemoteBackend
from tests.test_draft import png


class ImageContractTest(unittest.TestCase):
    def test_round_trip_and_shared_sdk_adapter(self):
        parts = encode_images([ImageAttachment('test.png', png())])
        self.assertEqual(decode_images(parts, 'gemini-3.5-flash-lite')[0].data, png())
        contents = to_gemini([{'role': 'user', 'content': 'describe', 'images': parts}])
        self.assertEqual(contents[0].parts[1].inline_data.data, png())
        self.assertFalse(validate_payload_images({'message': 'old client'}))

    def test_reject_invalid_model_mime_and_bytes(self):
        parts = encode_images([ImageAttachment('test.png', png())])
        for model, changes in [('unsupported', {}), ('gemini-3.5-flash-lite', {'data': '!'}),
                                ('gemini-3.5-flash-lite', {'mime_type': 'image/jpeg'})]:
            with self.assertRaises(ValueError):
                decode_images([{**parts[0], **changes}], model)

    def test_old_server_does_not_receive_text_only(self):
        http = Mock()
        http.get.return_value.status_code = 404
        remote = RemoteBackend('https://example.com', transport=http)
        result = remote.stream_chat({'message': 'describe', 'images': encode_images([ImageAttachment('a', png())])})
        self.assertEqual(result.status_code, 400)
        http.post.assert_not_called()
