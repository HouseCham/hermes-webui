import threading

import api.gateway_chat as gateway_chat
from api.gateway_chat import _build_gateway_attachment_message


def test_runs_api_payload_contains_text_not_local_attachment_path(tmp_path, monkeypatch):
    attachment = tmp_path / "pasted-text.md"
    attachment.write_text("payload content from the paste", encoding="utf-8")
    captured = {}

    class StopAtAdmission(Exception):
        pass

    def capture_admission(url, headers, body, stream_id):
        captured.update(body)
        raise StopAtAdmission

    monkeypatch.setattr(gateway_chat, "_admit_gateway_run", capture_admission)
    session = type("Session", (), {
        "context_messages": [],
        "truncation_watermark": None,
        "profile": None,
    })()

    try:
        gateway_chat._run_gateway_runs_api_streaming(
            "session-1", "review this", "test-model", str(tmp_path), "stream-1",
            "http://gateway.local", "", [], {},
            put_gateway_event=lambda *_args, **_kwargs: None,
            cancel_event=threading.Event(),
            attachments=[{"path": str(attachment), "name": attachment.name, "mime": "text/markdown"}],
            session=session,
        )
    except StopAtAdmission:
        pass

    assert captured["input"].startswith("review this")
    assert "payload content from the paste" in captured["input"]
    assert str(attachment) not in captured["input"]


def test_gateway_message_inlines_large_markdown_attachment(tmp_path):
    pasted = "# pasted text\n" + ("some long content\n" * 300)
    attachment = tmp_path / "pasted-text-2026-10-31_00-14-51-583.md"
    attachment.write_text(pasted, encoding="utf-8")

    result = _build_gateway_attachment_message(
        "Please review this", [{"path": str(attachment), "name": attachment.name, "mime": "text/markdown"}], str(tmp_path)
    )

    assert isinstance(result, str)
    assert "Please review this" in result
    assert f"[Attached text file: {attachment.name}]" in result
    assert pasted in result
    assert str(attachment) not in result


def test_gateway_message_inlines_text_attachment_with_image(tmp_path, monkeypatch):
    attachment_root = tmp_path / "attachments"
    attachment_root.mkdir()
    monkeypatch.setenv("HERMES_WEBUI_ATTACHMENT_DIR", str(attachment_root))
    inbox = attachment_root / "session"
    inbox.mkdir()
    doc = inbox / "notes.txt"
    doc.write_text("gateway-readable text", encoding="utf-8")
    image = inbox / "pixel.png"
    image.write_bytes(
        bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000b49444154789c63f80f00000101000518d84e0000000049454e44ae426082")
    )

    result = _build_gateway_attachment_message(
        "describe both", [
            {"path": str(image), "name": "pixel.png", "mime": "image/png", "is_image": True},
            {"path": str(doc), "name": "notes.txt", "mime": "text/plain"},
        ], str(tmp_path / "workspace")
    )

    assert isinstance(result, list)
    assert result[0] == {"type": "text", "text": "describe both"}
    assert any(part.get("type") == "image_url" for part in result)
    assert any("gateway-readable text" in part.get("text", "") for part in result)


def test_gateway_message_rejects_text_attachment_outside_allowed_roots(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("must not be disclosed", encoding="utf-8")

    result = _build_gateway_attachment_message(
        "read it", [{"path": str(outside), "name": outside.name, "mime": "text/plain"}], str(workspace)
    )

    assert "must not be disclosed" not in result


def test_gateway_message_skips_invalid_utf8_text_file(tmp_path):
    attachment = tmp_path / "bad.txt"
    attachment.write_bytes(b"\xff\xfe")

    result = _build_gateway_attachment_message(
        "prompt", [{"path": str(attachment), "name": attachment.name, "mime": "text/plain"}], str(tmp_path)
    )

    assert isinstance(result, str)
    assert "bad.txt" not in result


def test_gateway_message_keeps_text_attachment_total_bounded(tmp_path, monkeypatch):
    first = tmp_path / "one.md"
    second = tmp_path / "two.md"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    monkeypatch.setattr(gateway_chat, "MAX_UPLOAD_BYTES", 5)

    result = _build_gateway_attachment_message(
        "prompt", [
            {"path": str(first), "name": first.name, "mime": "text/markdown"},
            {"path": str(second), "name": second.name, "mime": "text/markdown"},
        ], str(tmp_path)
    )

    assert "first" in result
    assert "second" not in result
