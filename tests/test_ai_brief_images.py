"""AI Design takes reference images with a brief.

* an image is scaled down and encoded once (JPEG, or PNG when it has alpha);
* it rides on the request's last user message in each provider's own format;
* the conversation remembers that images were sent, not the pictures;
* the composer attaches pasted/dropped/picked images, at most four, and
  every request of the run carries them.
"""
import base64
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QObject, Signal  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.hmi_deployer.ai_design import (  # noqa: E402
    BYOK_PRESETS, MAX_BRIEF_IMAGES, MAX_IMAGE_SIDE, REFERENCE_IMAGES_NOTE, ODConnector,
    ProviderConfig, encode_brief_image, user_message,
)


def _image(width=40, height=20, alpha=False):
    image = QImage(width, height, QImage.Format_ARGB32 if alpha else QImage.Format_RGB32)
    image.fill(QColor(0, 0, 0, 0) if alpha else QColor("#2b6fb5"))
    return image


def _connector(provider, **extra):
    preset = dict(BYOK_PRESETS[provider], provider=provider, apiKey="k", model="m", **extra)
    return ODConnector(mode="byok", byok=ProviderConfig.from_dict(preset))


class Encoding(unittest.TestCase):
    def test_a_large_screenshot_is_scaled_and_sent_as_jpeg(self):
        image = encode_brief_image(_image(3000, 1000), "shot.png")
        self.assertEqual((image.mime, image.width), ("image/jpeg", MAX_IMAGE_SIDE))
        self.assertTrue(base64.b64decode(image.data).startswith(b"\xff\xd8"))

    def test_a_transparent_logo_stays_png(self):
        image = encode_brief_image(_image(alpha=True), "logo.png")
        self.assertEqual(image.mime, "image/png")
        self.assertTrue(image.data_url.startswith("data:image/png;base64,"))

    def test_an_unreadable_image_is_refused(self):
        with self.assertRaises(ValueError):
            encode_brief_image(QImage(), "broken.png")


class RequestShapes(unittest.TestCase):
    def setUp(self):
        self.images = [encode_brief_image(_image(), "ref.png")]

    def test_without_images_every_dialect_sends_plain_text(self):
        for provider in ("openai", "vllm", "ollama", "anthropic"):
            self.assertEqual(user_message(provider, "brief"), {"role": "user", "content": "brief"})

    def test_vllm_and_openai_send_image_parts(self):
        url, _headers, payload = _connector("ornith").byok_request("a cab", images=self.images)
        last = payload["messages"][-1]
        self.assertEqual(last["content"][0], {"type": "text", "text": "a cab"})
        self.assertEqual(last["content"][1]["image_url"]["url"], self.images[0].data_url)

    def test_ollama_sends_an_images_list(self):
        _url, _h, payload = _connector("ollama").byok_request("a cab", images=self.images)
        self.assertEqual(payload["messages"][-1]["images"], [self.images[0].data])

    def test_anthropic_sends_image_blocks_before_the_text(self):
        _url, _h, payload = _connector("anthropic").byok_request("a cab", images=self.images)
        content = payload["messages"][-1]["content"]
        self.assertEqual(content[0]["source"]["media_type"], self.images[0].mime)
        self.assertEqual(content[-1], {"type": "text", "text": "a cab"})

    def test_google_sends_inline_data(self):
        _url, _h, payload = _connector("google").byok_request("a cab", images=self.images)
        parts = payload["contents"][-1]["parts"]
        self.assertEqual(parts[0], {"text": "a cab"})
        self.assertEqual(parts[1]["inline_data"]["data"], self.images[0].data)

    def test_the_history_keeps_a_note_not_the_pictures(self):
        conn = _connector("ornith")
        with mock.patch.object(conn, "_stream_events", return_value=iter([])):
            list(conn.generate_events("a cab", images=self.images))
        self.assertIn("1 reference image(s) were attached", conn.conversation[0].content)
        _url, _h, payload = conn.byok_request("make it darker")
        for message in payload["messages"][:-1]:
            self.assertIsInstance(message["content"], str)


class _StubWorker(QObject):
    event = Signal(dict)
    finished = Signal()
    made = []

    def __init__(self, connector, brief, model, parent=None, images=None):
        super().__init__()
        _StubWorker.made.append((brief, list(images or [])))

    def start(self):
        pass


class Composer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _tab(self):
        from tools.hmi_deployer.ai_tab import AIDesignTab
        tab = AIDesignTab()
        self.addCleanup(tab.deleteLater)
        tab.connector = _connector("ornith")
        tab.model_combo.setEditText("ornith-1.5-35b-a3b")
        return tab

    def test_a_pasted_image_is_attached_not_inserted(self):
        tab = self._tab()
        mime = QMimeData()
        mime.setImageData(_image())
        self.assertTrue(tab.brief_input.canInsertFromMimeData(mime))
        tab.brief_input.insertFromMimeData(mime)
        self.assertEqual(len(tab.attachments()), 1)
        self.assertEqual(tab.brief_input.toPlainText(), "")
        self.assertFalse(tab.attachment_strip.isHidden())

    def test_at_most_four_and_one_can_be_removed(self):
        tab = self._tab()
        tab.add_images([_image() for _ in range(MAX_BRIEF_IMAGES + 2)])
        self.assertEqual(len(tab.attachments()), MAX_BRIEF_IMAGES)
        tab.remove_attachment(tab.attachments()[0])
        self.assertEqual(len(tab.attachments()), MAX_BRIEF_IMAGES - 1)

    def test_send_carries_the_images_and_clears_the_composer(self):
        tab = self._tab()
        tab.add_images([_image()])
        _StubWorker.made.clear()
        with mock.patch("tools.hmi_deployer.ai_tab.GenerationWorker", _StubWorker):
            tab._on_send()                               # no text: the image is the brief
        brief, images = _StubWorker.made[-1]
        self.assertEqual(len(images), 1)
        self.assertIn(REFERENCE_IMAGES_NOTE, brief)
        self.assertEqual(tab.attachments(), [])
        self.assertTrue(tab.attachment_strip.isHidden())
        self.assertEqual(len(tab.turns[-1].images), 1)


if __name__ == "__main__":
    unittest.main()
