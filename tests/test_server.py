import json
import signal
import wave
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server


def pcm_square_wave(amplitude: int, seconds: float, rate: int = 16000) -> bytes:
    sample_count = max(0, round(seconds * rate))
    if amplitude == 0:
        return b"\0\0" * sample_count
    positive = int(amplitude).to_bytes(2, "little", signed=True)
    negative = int(-amplitude).to_bytes(2, "little", signed=True)
    pairs, remainder = divmod(sample_count, 2)
    return (positive + negative) * pairs + (positive if remainder else b"")


def configure_tmp_app(monkeypatch, tmp_path):
    hermes_home = tmp_path / "hermes"
    audio_cache = hermes_home / "audio_cache"
    audio_cache.mkdir(parents=True)
    monkeypatch.setattr(server, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(server, "AUDIO_CACHE", audio_cache)
    monkeypatch.setattr(server, "UPLOAD_DIR", hermes_home / "voice_web_uploads")
    monkeypatch.setattr(server, "SESSIONS_FILE", hermes_home / "voice-web" / "sessions.json")
    monkeypatch.setattr(server, "REMINDERS_FILE", hermes_home / "voice-web" / "reminders.json")
    with server.PI_RECORD_LOCK:
        server.PI_RECORD_JOBS.clear()
    return TestClient(server.app), audio_cache


def css_block(source: str, header: str) -> str:
    header_start = source.index(header)
    block_start = source.index("{", header_start + len(header))
    depth = 1
    for index in range(block_start + 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[block_start + 1 : index]
    raise AssertionError(f"Unclosed CSS block: {header}")


def test_session_crud(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)

    created = client.post("/api/sessions", json={"title": "测试会话"})
    assert created.status_code == 200
    session = created.json()["session"]
    assert session["title"] == "测试会话"

    listed = client.get("/api/sessions")
    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["id"] == session["id"]

    renamed = client.patch(f"/api/sessions/{session['id']}", json={"title": "新标题"})
    assert renamed.status_code == 200
    assert renamed.json()["session"]["title"] == "新标题"

    deleted = client.delete(f"/api/sessions/{session['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["sessions"] == []


def test_reminder_crud(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)

    created = client.post("/api/reminders", json={"text": "交数学作业", "due_text": "明天 09:00"})
    assert created.status_code == 200
    reminder = created.json()["reminder"]
    assert reminder["text"] == "交数学作业"
    assert reminder["done"] is False

    listed = client.get("/api/reminders")
    assert listed.status_code == 200
    assert listed.json()["reminders"][0]["id"] == reminder["id"]

    completed = client.patch(f"/api/reminders/{reminder['id']}", json={"done": True})
    assert completed.status_code == 200
    assert completed.json()["reminder"]["done"] is True

    reopened = client.patch(f"/api/reminders/{reminder['id']}", json={"done": "false"})
    assert reopened.status_code == 200
    assert reopened.json()["reminder"]["done"] is False

    completed = client.patch(f"/api/reminders/{reminder['id']}", json={"done": "true"})
    assert completed.status_code == 200
    assert completed.json()["reminder"]["done"] is True

    open_list = client.get("/api/reminders")
    assert open_list.status_code == 200
    assert open_list.json()["reminders"] == []

    deleted = client.delete(f"/api/reminders/{reminder['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["reminders"] == []


def test_index_uses_xiaoqi_brand_and_visible_playback_controls(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Hermes 控制台" not in response.text
    assert "生活助手小七" in response.text
    assert "浏览器播放语音回复" in response.text
    assert "小七音箱播放语音回复" in response.text
    assert "使用当前浏览器麦克风" in response.text
    assert "使用小七树莓派麦克风" in response.text
    assert "输入设备" in response.text
    assert "输出设备" in response.text
    assert "智能助手录音" in response.text
    assert "树莓派录音" not in response.text
    assert "语音模式" in response.text
    assert "开启语音" in response.text
    assert "结束语音" in response.text
    assert "自动电话模式" not in response.text
    assert "开始通话" not in response.text
    assert "挂断" not in response.text
    assert '<link rel="stylesheet" href="/app.css" />' in response.text
    assert '<script src="/call-mode.js"></script>' in response.text
    assert '<script src="/ui-motion.js"></script>' in response.text
    assert response.text.index('<script src="/call-mode.js"></script>') < response.text.index(
        '<script src="/ui-motion.js"></script>'
    )
    assert "http://localhost:18787" not in response.text
    assert "https://pi5.local:8787/" in response.text
    assert "浏览器转写不可用，继续使用后端转写。" in response.text
    assert response.text.index('class="side-stack"') < response.text.index('class="panel chat-panel"')
    assert response.text.index('class="panel chat-panel"') < response.text.index('class="panel sidebar"')

    start_call = css_block(response.text, "async function startCall()")
    assert 'state.playTarget = "browser"' not in start_call
    assert "selectedInputAvailable()" in start_call
    assert "小七麦克风" in start_call
    assert "小七音箱" in start_call
    assert "waitForCompletion: true" in response.text
    assert "piCallEndpointSummary" in response.text
    assert "说完安静约" in response.text
    assert "小七自动收句" in response.text

    capture_call = css_block(response.text, "async function captureCallTurn({ signal })")
    assert 'state.inputTarget === "pi"' in capture_call
    assert "capturePiCallTurn" in capture_call

    capture_pi = css_block(response.text, "async function capturePiCallTurn({ signal })")
    assert "stream: true" in capture_pi
    assert 'kind: "pi_stream"' in capture_pi
    assert '["processing", "streaming"]' in capture_pi

    stream_playback = css_block(response.text, "async function playPiStreamingReply(data, { signal })")
    assert "piStreamingSegments" in stream_playback
    assert "waitForCompletion: true" in stream_playback
    assert "stopPiCallJob" in stream_playback

    manual_pi = css_block(response.text, "async function startPiRecording()")
    assert "stream: false" in manual_pi


def test_call_mode_asset_is_served_without_cache(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)

    response = client.get("/call-mode.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/javascript")
    assert "createCallController" in response.text
    assert 'LISTENING: "listening"' in response.text


def test_design_assets_are_served_without_cache(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)

    css = client.get("/app.css")
    motion = client.get("/ui-motion.js")

    assert css.status_code == 200
    assert css.headers["cache-control"] == "no-store"
    assert css.headers["content-type"].startswith("text/css")
    assert "--accent:" in css.text
    assert "color-scheme: light" in css.text
    assert "#0071e3" in css.text
    assert "prefers-reduced-motion" in css.text

    assert motion.status_code == 200
    assert motion.headers["cache-control"] == "no-store"
    assert motion.headers["content-type"].startswith("text/javascript")
    assert "XiaoQiUI" in motion.text
    assert "reduceMotion" in motion.text


def test_tablet_two_column_shell_keeps_voice_area_in_one_column():
    css = server.APP_CSS_FILE.read_text(encoding="utf-8")
    tablet_shell_layout = css_block(css, "@media (max-width: 1120px)")
    shell = css_block(tablet_shell_layout, ".shell")
    tablet = css_block(css, "@media (min-width: 821px) and (max-width: 1120px)")
    side_stack = css_block(tablet, ".side-stack")

    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in shell
    assert "grid-template-columns: minmax(0, 1fr);" in side_stack
    assert "grid-auto-flow: row;" in side_stack


def test_device_routing_is_explicit_and_mobile_safe():
    css = server.APP_CSS_FILE.read_text(encoding="utf-8")
    routing = css_block(css, ".device-routing")
    mobile = css_block(css, "@media (max-width: 560px)")
    mobile_routing = css_block(mobile, ".device-routing")

    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in routing
    assert "grid-template-columns: minmax(0, 1fr);" in mobile_routing


def test_short_desktop_sidebar_can_scroll_expanded_session_settings():
    css = server.APP_CSS_FILE.read_text(encoding="utf-8")
    sidebar = css_block(css, ".sidebar")
    session_list = css_block(css, ".session-list")
    session_tools = css_block(css[css.index(".session-list") :], ".session-tools")

    assert "max-height: calc(100svh - 112px);" in sidebar
    assert "overflow-y: auto;" in sidebar
    assert "overscroll-behavior-y: contain;" in sidebar
    assert "min-height: 0;" in session_list
    assert "overflow: auto;" in session_list
    assert "flex: 0 0 auto;" in session_tools


def test_short_desktop_chat_composer_remains_reachable():
    css = server.APP_CSS_FILE.read_text(encoding="utf-8")
    short_desktop = css_block(css, "@media (min-width: 1121px) and (max-height: 640px)")
    chat_panel = css_block(short_desktop, ".chat-panel")

    assert "min-height: 360px;" in chat_panel
    assert "max-height: none;" in chat_panel
    assert "grid-template-rows: auto minmax(0, 1fr) auto;" in chat_panel


def test_chat_saves_exchange(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_run_hermes", lambda prompt: "这是回复")

    response = client.post("/api/chat", json={"message": "你好"})
    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "这是回复"
    assert data["session"]["messages"][0]["content"] == "你好"
    assert data["session"]["messages"][1]["content"] == "这是回复"

    stored = json.loads(server.SESSIONS_FILE.read_text(encoding="utf-8"))
    assert stored["sessions"][0]["messages"][1]["role"] == "assistant"


def test_clean_reply_replaces_denied_command_output():
    raw = """⚠️  DANGEROUS COMMAND: script execution via -e/-c flag
      curl -s "wttr.in/Tianjin?format=j1" | python3 -c "print(1)"
      [o]nce  |  [s]ession  |  [a]lways  |  [d]eny
      Choice [o/s/a/D]:       ✗ Denied"""

    reply = server._clean_reply(raw)

    assert reply == server.COMMAND_DENIED_REPLY
    assert "DANGEROUS COMMAND" not in reply
    assert "Denied" not in reply


def test_clean_reply_removes_hermes_runtime_notice():
    raw = """⚠️  Reached maximum iterations (1). Requesting summary...
天津现在阴天，气温24°C。"""

    reply = server._clean_reply(raw)

    assert reply == "天津现在阴天，气温24°C。"
    assert "maximum iterations" not in reply


def test_clean_reply_removes_hermes_v021_tirith_notice():
    raw = """⚠ tirith security scanner enabled but not available — command scanning will use pattern matching only
旁路Hermes正常"""

    reply = server._clean_reply(raw)

    assert reply == "旁路Hermes正常"
    assert "tirith security scanner" not in reply


def test_plain_speech_reply_strips_common_markdown():
    raw = """同学你好！
**当前：** 阴天，气温 30°C
- 建议穿**短袖、薄T恤**
- 出门记得`带伞`
- 长时间户外要*防晒*"""

    reply = server._plain_speech_reply(raw)

    assert reply == "同学你好！ 当前：阴天，气温 30°C 建议穿短袖、薄T恤 出门记得带伞 长时间户外要防晒"
    assert "**" not in reply
    assert "- " not in reply
    assert "`" not in reply
    assert "*" not in reply


def test_voice_reply_segmenter_emits_first_sentence_early_without_truncating_reply():
    reply = "先给你结论。接下来这一段会继续详细说明原因，同时保留完整的长回复内容。最后再给出可以立即执行的建议！"
    segmenter = server._VoiceReplySegmenter(first_limit=24, later_limit=32)
    segments = []
    for offset in range(0, len(reply), 7):
        segments.extend(segmenter.feed(reply[offset : offset + 7]))
    segments.extend(segmenter.finish())

    assert segments[0] == "先给你结论。"
    assert len(segments) >= 3
    assert "".join(segments) == reply
    assert all(len(segment) <= 32 for segment in segments)


def test_deepseek_stream_yields_deltas_and_closes_stream(monkeypatch):
    class Delta:
        def __init__(self, content):
            self.content = content

    class Choice:
        def __init__(self, content):
            self.delta = Delta(content)

    class Event:
        def __init__(self, content):
            self.choices = [Choice(content)]

    class Stream:
        def __init__(self):
            self.events = iter([Event("第一句。"), Event(""), Event("第二句。")])
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.events)

        def close(self):
            self.closed = True

    class Completions:
        def __init__(self, stream):
            self.stream = stream
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return self.stream

    stream = Stream()
    completions = Completions(stream)
    client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    monkeypatch.setattr(
        server,
        "_deepseek_stream_settings",
        lambda: {"model": "deepseek-v4-flash", "base_url": "https://example.invalid", "api_key": "secret"},
    )
    monkeypatch.setattr(server, "_deepseek_client", lambda settings: client)

    reply = "".join(server._stream_deepseek_reply("测试提示"))

    assert reply == "第一句。第二句。"
    assert completions.kwargs == {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "测试提示"}],
        "stream": True,
    }
    assert stream.closed is True


def test_deepseek_stream_redacts_api_key_from_errors(monkeypatch):
    class BrokenCompletions:
        def create(self, **kwargs):
            raise RuntimeError("provider rejected test-secret-key")

    client = type("Client", (), {"chat": type("Chat", (), {"completions": BrokenCompletions()})()})()
    monkeypatch.setattr(
        server,
        "_deepseek_stream_settings",
        lambda: {
            "model": "deepseek-v4-flash",
            "base_url": "https://example.invalid",
            "api_key": "test-secret-key",
        },
    )
    monkeypatch.setattr(server, "_deepseek_client", lambda settings: client)

    with pytest.raises(server.HTTPException) as raised:
        list(server._stream_deepseek_reply("测试"))

    assert raised.value.status_code == 502
    assert "test-secret-key" not in str(raised.value.detail)
    assert "[redacted]" in str(raised.value.detail)


def test_streaming_voice_job_saves_full_reply_after_exposing_segments(monkeypatch, tmp_path):
    client, audio_cache = configure_tmp_app(monkeypatch, tmp_path)
    created = client.post("/api/sessions", json={"title": "流式语音测试"}).json()["session"]
    job_id = "streamjob"
    with server.PI_RECORD_LOCK:
        server.PI_RECORD_JOBS[job_id] = {
            "id": job_id,
            "status": "processing",
            "stage": "transcribing",
            "duration": 8,
            "elapsed": 2,
            "session_id": created["id"],
            "started_at": server._now(),
            "started_monotonic": server.time.monotonic(),
            "completed_at": None,
            "stop_requested": False,
            "segments": [],
            "timing": {},
        }

    chunks = ["先给你结论。", "原因我会继续说清楚。", "最后给你一个可执行建议。"]
    monkeypatch.setattr(
        server,
        "_iter_streaming_voice_reply",
        lambda session, user_text, is_cancelled: iter(chunks),
    )
    generated = []

    def fake_speak(text):
        path = audio_cache / f"segment-{len(generated)}.mp3"
        path.write_bytes(f"audio:{text}".encode())
        generated.append(text)
        return {"audio_url": f"/audio/{path.name}", "tts": {"provider": "fake"}}

    monkeypatch.setattr(server, "_speak_reply", fake_speak)
    monkeypatch.setattr(server, "_combine_voice_segments", lambda segments: "/audio/combined.mp3")

    result = server._stream_voice_answer_for_pi_job(job_id, "请详细回答", 2, created["id"])

    assert result["streaming"] is True
    assert result["reply"] == "".join(chunks)
    assert result["audio_url"] == "/audio/combined.mp3"
    assert [segment["text"] for segment in result["audio_segments"]] == chunks
    assert generated == chunks
    with server.PI_RECORD_LOCK:
        job = server.PI_RECORD_JOBS[job_id]
        assert job["status"] == "streaming"
        assert job["transcript"] == "请详细回答"
        assert "first_audio_ready_ms" in job["timing"]
        assert "generation_completed_ms" in job["timing"]
    saved = client.get(f"/api/sessions/{created['id']}").json()["session"]
    assert saved["messages"][-1]["content"] == "".join(chunks)
    assert len(saved["messages"][-1]["audio_segments"]) == 3


def test_normalise_message_replaces_stored_denied_command_output():
    message = {
        "id": "bad",
        "role": "assistant",
        "content": "⚠️  DANGEROUS COMMAND: script execution via -e/-c flag\nChoice [o/s/a/D]: ✗ Denied",
        "kind": "voice",
    }

    normalised = server._normalise_message(message)

    assert normalised["content"] == server.COMMAND_DENIED_REPLY


def test_normalise_message_removes_stored_runtime_notice():
    message = {
        "id": "warn",
        "role": "assistant",
        "content": "⚠️ Reached maximum iterations (1). Requesting summary...\n天津现在阴天。",
        "kind": "text",
    }

    normalised = server._normalise_message(message)

    assert normalised["content"] == "天津现在阴天。"


def test_run_hermes_limits_voice_web_tool_loop(monkeypatch):
    captured = {}

    class Completed:
        returncode = 0
        stdout = "好的"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(server, "_find_hermes_cli", lambda: "/usr/bin/hermes")
    monkeypatch.setattr(server.subprocess, "run", fake_run)

    assert server._run_hermes("你好") == "好的"
    assert captured["command"][-4:] == ["--source", "voice-web", "--max-turns", str(server.HERMES_MAX_TURNS)]
    assert captured["kwargs"]["env"]["HERMES_HOME"] == str(server.HERMES_HOME)


def test_chat_prompt_uses_xiaoqi_student_identity(monkeypatch):
    monkeypatch.setattr(server, "ASSISTANT_NAME", "生活助手小七")
    monkeypatch.setattr(server, "USER_NAME", "Soul")
    monkeypatch.setattr(server, "USER_PROFILE", "学生，需要你帮助完成学习上的事情。")

    prompt = server._build_chat_prompt(
        [
            {"role": "user", "content": "我今天数学不会"},
            {"role": "assistant", "content": "先把题目发我。"},
        ],
        "帮我安排复习",
    )

    assert "你是生活助手小七" in prompt
    assert "Soul的身份画像：学生" in prompt
    assert "优先帮助用户完成学习上的事情" in prompt
    assert "不能执行 shell 命令" in prompt
    assert "WEATHER_CONTEXT" in prompt
    assert "BRIEFING_CONTEXT" in prompt
    assert "REMINDER_CONTEXT" in prompt
    assert "不要编造结果" in prompt
    assert "Soul: 我今天数学不会" in prompt
    assert "生活助手小七: 先把题目发我。" in prompt
    assert prompt.endswith("生活助手小七:")


def test_reminder_chat_creates_local_reminder(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)
    monkeypatch.setattr(
        server,
        "_run_hermes",
        lambda prompt: (_ for _ in ()).throw(AssertionError("Hermes should not run for local reminder creation")),
    )

    response = client.post("/api/chat", json={"message": "提醒我明天上午九点交数学作业"})

    assert response.status_code == 200
    data = response.json()
    assert "已记下本地提醒" in data["reply"]
    reminders = json.loads(server.REMINDERS_FILE.read_text(encoding="utf-8"))["reminders"]
    assert reminders[0]["text"] == "交数学作业"
    assert reminders[0]["due_at"]
    assert reminders[0]["done"] is False


def test_reminder_text_keeps_non_time_leading_numbers():
    assert server._extract_reminder_create_payload("提醒我 20 个单词")["text"] == "20 个单词"
    assert server._extract_reminder_create_payload("提醒我三篇论文")["text"] == "三篇论文"
    payload = server._extract_reminder_create_payload("提醒我5月20号交材料")
    assert payload["text"] == "交材料"
    assert payload["due_precision"] == "date"


def test_reminder_chat_lists_local_reminders(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)
    server._create_reminder("背英语单词", due_text="今晚")
    monkeypatch.setattr(
        server,
        "_run_hermes",
        lambda prompt: (_ for _ in ()).throw(AssertionError("Hermes should not run for local reminder listing")),
    )

    response = client.post("/api/chat", json={"message": "我的提醒"})

    assert response.status_code == 200
    assert "背英语单词" in response.json()["reply"]


def test_extract_weather_location_from_chinese_query():
    assert server._extract_weather_location("帮我查一下上海今天的天气") == "上海"
    assert server._extract_weather_location("小七给我查一下天津天气") == "天津"
    assert server._extract_weather_location("小七给我 一下 天津的天气") == "天津"
    assert server._extract_weather_location("明天北京会不会下雨") == "北京"
    assert server._extract_weather_location("今天天气怎么样") is None


def test_weather_chat_injects_context(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)
    captured = {}

    def fake_run(prompt):
        captured["prompt"] = prompt
        return "上海现在 24°C，建议带伞。"

    monkeypatch.setattr(server, "_build_weather_context_for_text", lambda text: "WEATHER_CONTEXT:\n地点：上海\n当前：小雨")
    monkeypatch.setattr(server, "_run_hermes", fake_run)

    response = client.post("/api/chat", json={"message": "上海天气怎么样"})

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "上海现在 24°C，建议带伞。"
    assert "WEATHER_CONTEXT" in captured["prompt"]
    assert "地点：上海" in captured["prompt"]


def test_weather_chat_asks_for_location_without_city(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "WEATHER_DEFAULT_LOCATION", "")
    monkeypatch.setattr(
        server,
        "_run_hermes",
        lambda prompt: (_ for _ in ()).throw(AssertionError("Hermes should not run without a weather location")),
    )

    response = client.post("/api/chat", json={"message": "今天天气怎么样"})

    assert response.status_code == 200
    assert "城市" in response.json()["reply"]


def test_volcengine_stt_status_reports_missing_requirements(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_hermes_config",
        lambda: {"stt": {"enabled": True, "provider": "volcengine", "volcengine": {"access_key": "token"}}},
    )
    monkeypatch.delenv("VOLCENGINE_ASR_APP_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_ASR_CLUSTER", raising=False)
    monkeypatch.delenv("VOLCENGINE_CLUSTER", raising=False)

    status = server._stt_status()

    assert status["provider"] == "volcengine"
    assert status["ready"] is False
    assert "app_key" in status["detail"]
    assert "cluster" in status["detail"]
    assert status["runtime"] == "volcengine-v2-ws"


def test_volcengine_transcript_extraction_handles_common_shapes():
    assert server._extract_volcengine_transcript({"text": "你好"}) == "你好"
    assert server._extract_volcengine_transcript({"result": {"text": "天津天气"}}) == "天津天气"
    assert server._extract_volcengine_transcript({"result": {"utterances": [{"text": "天津"}, {"text": "天气"}]}}) == "天津天气"


def test_stt_provider_statuses_include_volcengine_missing(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_hermes_config",
        lambda: {"stt": {"enabled": True, "provider": "local", "volcengine": {"access_key": "token"}}},
    )
    monkeypatch.delenv("VOLCENGINE_ASR_APP_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_ASR_CLUSTER", raising=False)
    monkeypatch.delenv("VOLCENGINE_CLUSTER", raising=False)

    status = server._stt_provider_statuses()["volcengine"]

    assert status["ready"] is False
    assert status["missing"] == ["app_key", "cluster"]
    assert status["runtime"] == "volcengine-v2-ws"


def test_weather_endpoint_formats_open_meteo_payload(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)

    monkeypatch.setattr(
        server,
        "_fetch_weather",
        lambda location: {
            "requested_location": location,
            "source": "Open-Meteo",
            "timezone": "Asia/Shanghai",
            "resolved_location": {
                "name": "上海",
                "admin1": "上海市",
                "country": "中国",
                "latitude": 31.22222,
                "longitude": 121.45806,
            },
            "current": {
                "time": "2026-05-13T18:00",
                "temperature_2m": 24.2,
                "apparent_temperature": 25.0,
                "relative_humidity_2m": 70,
                "precipitation": 0.4,
                "weather_code": 61,
                "cloud_cover": 80,
                "wind_speed_10m": 11.0,
                "wind_direction_10m": 90,
            },
            "daily": {
                "time": ["2026-05-13"],
                "weather_code": [61],
                "temperature_2m_min": [20],
                "temperature_2m_max": [26],
                "precipitation_probability_max": [70],
                "precipitation_sum": [3.2],
                "wind_speed_10m_max": [18],
                "uv_index_max": [4.8],
            },
        },
    )

    response = client.get("/api/weather?location=上海")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["source"] == "Open-Meteo"
    assert "上海 / 上海市 / 中国" in data["context"]
    assert "小雨" in data["context"]


def test_briefing_chat_injects_context(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)
    captured = {}

    monkeypatch.setattr(server, "_build_briefing_context_for_text", lambda text: "BRIEFING_CONTEXT:\nSYSTEM_CONTEXT:\n服务状态正常")

    def fake_run(prompt):
        captured["prompt"] = prompt
        return "早安，今天服务正常。"

    monkeypatch.setattr(server, "_run_hermes", fake_run)

    response = client.post("/api/chat", json={"message": "今日简报"})

    assert response.status_code == 200
    assert response.json()["reply"] == "早安，今天服务正常。"
    assert "BRIEFING_CONTEXT" in captured["prompt"]
    assert "服务状态正常" in captured["prompt"]


def test_briefing_endpoint_returns_system_context(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)
    server._create_reminder("复习线性代数", due_text="今天")
    monkeypatch.setattr(
        server,
        "_system_snapshot",
        lambda: {
            "time_local": "2026-05-14T08:00+08:00",
            "hostname": "pi5",
            "cpu_count": 4,
            "load_average": (0.1, 0.2, 0.3),
            "memory_used_percent": 42.5,
            "memory_total_mb": 8192,
            "disk_used_percent": 55.0,
            "disk_free_gb": 12.3,
            "temperature_c": 49.1,
            "uptime_seconds": 3660,
            "services": {"hermes-voice-web": "active", "resp-lanu": "active"},
        },
    )
    monkeypatch.setattr(server, "_fetch_weather", lambda location: (_ for _ in ()).throw(server.WeatherLookupError("offline")))

    response = client.get("/api/briefing?location=天津")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["location"] == "天津"
    assert data["weather_available"] is False
    assert data["reminder_count"] == 1
    assert "BRIEFING_CONTEXT" in data["context"]
    assert "REMINDER_CONTEXT" in data["context"]
    assert "复习线性代数" in data["context"]
    assert "SYSTEM_CONTEXT" in data["context"]
    assert "hermes-voice-web=active" in data["context"]


def test_voice_response_creates_audio_url(monkeypatch, tmp_path):
    client, audio_cache = configure_tmp_app(monkeypatch, tmp_path)
    audio_file = audio_cache / "reply.ogg"
    audio_file.write_bytes(b"OggS test")

    monkeypatch.setattr(server, "_run_hermes", lambda prompt: "语音回复")
    monkeypatch.setattr(server, "_text_to_speech", lambda text: json.dumps({"file_path": str(audio_file)}))

    response = client.post("/api/respond", json={"transcript": "今天天气怎么样", "duration": 5})
    assert response.status_code == 200
    data = response.json()
    assert data["transcript"] == "今天天气怎么样"
    assert data["audio_url"] == "/audio/reply.ogg"

    audio = client.get(data["audio_url"])
    assert audio.status_code == 200
    assert audio.content == b"OggS test"


def test_audio_route_rejects_directories(monkeypatch, tmp_path):
    client, audio_cache = configure_tmp_app(monkeypatch, tmp_path)
    (audio_cache / "not-a-file").mkdir()

    response = client.get("/audio/not-a-file")

    assert response.status_code == 404


def test_voice_response_returns_plain_text_for_tts(monkeypatch, tmp_path):
    client, audio_cache = configure_tmp_app(monkeypatch, tmp_path)
    audio_file = audio_cache / "reply.ogg"
    audio_file.write_bytes(b"OggS test")
    captured = {}

    monkeypatch.setattr(
        server,
        "_run_hermes",
        lambda prompt: "同学你好！\n**当前：** 阴天，气温 30°C\n- 建议穿**短袖**\n- 出门记得`带伞`",
    )

    def fake_tts(text):
        captured["tts_text"] = text
        return json.dumps({"file_path": str(audio_file)})

    monkeypatch.setattr(server, "_text_to_speech", fake_tts)

    response = client.post("/api/respond", json={"transcript": "天津天气怎么样", "duration": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "同学你好！ 当前：阴天，气温 30°C 建议穿短袖 出门记得带伞"
    assert data["message"]["content"] == data["reply"]
    assert captured["tts_text"] == data["reply"]
    assert "**" not in data["reply"]
    assert "- " not in data["reply"]
    assert "`" not in data["reply"]


def test_voice_response_bypasses_service_weather_intent(monkeypatch, tmp_path):
    client, audio_cache = configure_tmp_app(monkeypatch, tmp_path)
    audio_file = audio_cache / "reply.ogg"
    audio_file.write_bytes(b"OggS test")
    captured = {}

    def fake_run(prompt):
        captured["prompt"] = prompt
        return "Hermes 直接处理语音"

    monkeypatch.setattr(
        server,
        "_build_weather_context_for_text",
        lambda text: (_ for _ in ()).throw(AssertionError("voice should not use service weather intent")),
    )
    monkeypatch.setattr(server, "_run_hermes", fake_run)
    monkeypatch.setattr(server, "_text_to_speech", lambda text: json.dumps({"file_path": str(audio_file)}))

    response = client.post("/api/respond", json={"transcript": "小七给我 一下 天津的天气", "duration": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Hermes 直接处理语音"
    assert "语音转写" in captured["prompt"]
    assert "小七给我 一下 天津的天气" in captured["prompt"]
    assert "WEATHER_CONTEXT" not in captured["prompt"]
    assert "纯文本中文口语" in captured["prompt"]
    assert "不要使用 Markdown" in captured["prompt"]


def test_pi_playback_endpoint_plays_cached_audio(monkeypatch, tmp_path):
    client, audio_cache = configure_tmp_app(monkeypatch, tmp_path)
    audio_file = audio_cache / "reply.ogg"
    audio_file.write_bytes(b"OggS test")
    launched = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            launched.append((command, kwargs))

    monkeypatch.setattr(server, "PI_PLAYBACK_COMMAND", "player --quiet")
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/player" if name == "player" else None)
    monkeypatch.setattr(server.subprocess, "Popen", FakeProcess)

    response = client.post("/api/pi-playback", json={"audio_url": "/audio/reply.ogg"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert launched[0][0] == ["/usr/bin/player", "--quiet", str(audio_file)]
    assert launched[0][1]["start_new_session"] is True


def test_pi_playback_prefers_direct_alsa_device(monkeypatch, tmp_path):
    client, audio_cache = configure_tmp_app(monkeypatch, tmp_path)
    audio_file = audio_cache / "reply.ogg"
    audio_file.write_bytes(b"OggS test")
    launched = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.command = command
            self.returncode = None
            self.stdout = BytesIO(b"wav") if "ffmpeg" in command[0] else None
            launched.append((command, kwargs, self))

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(server, "PI_PLAYBACK_COMMAND", "")
    monkeypatch.setattr(server, "_direct_alsa_playback_device", lambda: "plughw:CARD=vc4hdmi0,DEV=0")
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "aplay"} else None)
    monkeypatch.setattr(server.subprocess, "Popen", FakeProcess)

    response = client.post("/api/pi-playback", json={"audio_url": "/audio/reply.ogg"})

    assert response.status_code == 200
    assert response.json()["player"] == "ffmpeg+aplay"
    assert response.json()["device"] == "plughw:CARD=vc4hdmi0,DEV=0"
    assert launched[0][0][:3] == ["/usr/bin/ffmpeg", "-nostdin", "-loglevel"]
    assert launched[1][0] == ["/usr/bin/aplay", "-q", "-D", "plughw:CARD=vc4hdmi0,DEV=0", "-"]
    assert launched[1][1]["stdin"] is launched[0][2].stdout


def test_pi_playback_can_wait_for_half_duplex_call(monkeypatch, tmp_path):
    client, audio_cache = configure_tmp_app(monkeypatch, tmp_path)
    audio_file = audio_cache / "reply.ogg"
    audio_file.write_bytes(b"OggS test")
    waited = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.command = command
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout=None):
            waited.append(timeout)
            self.returncode = 0
            return 0

    monkeypatch.setattr(server, "PI_PLAYBACK_COMMAND", "player --quiet")
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/player" if name == "player" else None)
    monkeypatch.setattr(server.subprocess, "Popen", FakeProcess)

    response = client.post("/api/pi-playback", json={"audio_url": "/audio/reply.ogg", "wait": True})

    assert response.status_code == 200
    assert response.json()["completed"] is True
    assert waited == [server.PI_PLAYBACK_TIMEOUT]


def test_pi_playback_autodetects_non_hdmi_output(monkeypatch):
    monkeypatch.setattr(server, "PI_PLAYBACK_COMMAND", "")
    monkeypatch.setattr(server, "PI_PLAYBACK_DEVICE", "")
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "aplay"} else None)
    monkeypatch.setattr(
        server,
        "_alsa_hardware_devices",
        lambda command: [
            {"device": "plughw:CARD=vc4hdmi0,DEV=0", "card_name": "vc4hdmi0", "card_label": "vc4-hdmi-0"},
            {"device": "plughw:CARD=M83,DEV=0", "card_name": "M83", "card_label": "USB Audio"},
        ]
        if command == "aplay"
        else [],
    )

    status = server._pi_playback_status()

    assert status["ready"] is True
    assert status["device"] == "plughw:CARD=M83,DEV=0"
    assert status["candidate_devices"][0]["device"] == "plughw:CARD=M83,DEV=0"


def test_pi_playback_endpoint_rejects_audio_traversal(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "PI_PLAYBACK_COMMAND", "/usr/bin/player")

    response = client.post("/api/pi-playback", json={"audio_url": "/audio/../../etc/passwd"})

    assert response.status_code == 404


def test_pi_record_status_reports_arecord(monkeypatch):
    monkeypatch.setattr(server, "_find_arecord", lambda: "/usr/bin/arecord")
    monkeypatch.setattr(server, "PI_RECORD_DEVICE", "plughw:CARD=Device,DEV=0")
    monkeypatch.setattr(server, "PI_RECORD_RATE", 16000)
    monkeypatch.setattr(server, "PI_RECORD_CHANNELS", 1)

    status = server._pi_record_status()

    assert status["available"] is True
    assert status["ready"] is True
    assert status["recorder"] == "/usr/bin/arecord"
    assert status["device"] == "plughw:CARD=Device,DEV=0"


def test_pi_record_status_requires_capture_hardware(monkeypatch):
    monkeypatch.setattr(server, "_find_arecord", lambda: "/usr/bin/arecord")
    monkeypatch.setattr(server, "PI_RECORD_DEVICE", "")
    monkeypatch.setattr(server, "_alsa_hardware_devices", lambda command: [])

    status = server._pi_record_status()

    assert status["available"] is False
    assert status["ready"] is False
    assert status["device"] is None
    assert "capture hardware" in status["detail"]


def test_pi_record_autodetects_capture_hardware(monkeypatch):
    monkeypatch.setattr(server, "_find_arecord", lambda: "/usr/bin/arecord")
    monkeypatch.setattr(server, "PI_RECORD_DEVICE", "")
    monkeypatch.setattr(
        server,
        "_alsa_hardware_devices",
        lambda command: [
            {"device": "plughw:CARD=Mic,DEV=0", "card_name": "Mic", "card_label": "USB Microphone"},
        ]
        if command == "arecord"
        else [],
    )

    status = server._pi_record_status()

    assert status["available"] is True
    assert status["ready"] is True
    assert status["device"] == "plughw:CARD=Mic,DEV=0"
    assert status["candidate_devices"] == ["plughw:CARD=Mic,DEV=0"]
    assert status["endpointing"]["enabled"] is True
    assert status["endpointing"]["silence_seconds"] == 1.0
    assert status["endpointing"]["min_rms"] == 0.0052
    assert status["endpointing"]["min_speech_seconds"] == 0.3
    assert status["endpointing"]["noise_multiplier"] == 1.6
    assert status["endpointing"]["release_multiplier"] == 1.35


def test_pi_voice_endpoint_detector_stops_after_speech_and_silence():
    detector = server._PiVoiceEndpointDetector(
        rate=16000,
        channels=1,
        silence_seconds=1.0,
        no_speech_seconds=5.0,
        min_speech_seconds=0.2,
        min_rms=0.008,
        noise_multiplier=2.5,
        calibration_seconds=0.25,
    )

    assert detector.feed(pcm_square_wave(0, 0.25)) is None
    assert detector.feed(pcm_square_wave(5000, 0.3)) is None
    assert detector.speech_detected is True
    assert detector.feed(pcm_square_wave(0, 1.1)) == "silence"
    assert 1.5 <= detector.elapsed_seconds < 1.7


def test_pi_voice_endpoint_detector_bounds_empty_turn():
    detector = server._PiVoiceEndpointDetector(
        rate=16000,
        channels=1,
        silence_seconds=1.0,
        no_speech_seconds=0.6,
        min_speech_seconds=0.2,
        min_rms=0.008,
        noise_multiplier=2.5,
        calibration_seconds=0.2,
    )

    assert detector.feed(pcm_square_wave(0, 0.7)) == "no_speech"
    assert detector.speech_detected is False


def test_pi_voice_endpoint_detector_accepts_measured_low_gain_pi_signal():
    detector = server._PiVoiceEndpointDetector(
        rate=16000,
        channels=1,
        silence_seconds=1.0,
        no_speech_seconds=5.0,
        min_speech_seconds=0.2,
        min_rms=0.0052,
        noise_multiplier=1.6,
        release_multiplier=1.35,
        calibration_seconds=0.25,
    )

    # XiaoQi's measured ambient RMS is about 0.011. The trigger must stay
    # above that floor, while normal nearby speech around 0.027 still starts
    # the turn and the measured ambient level releases it again.
    assert detector.feed(pcm_square_wave(360, 0.25)) is None
    assert detector.feed(pcm_square_wave(900, 0.3)) is None
    assert detector.speech_detected is True
    assert 0.017 <= detector.trigger_threshold <= 0.018
    assert detector.feed(pcm_square_wave(360, 1.1)) == "silence"


def test_pi_voice_endpoint_detector_does_not_calibrate_early_speech_away():
    detector = server._PiVoiceEndpointDetector(
        rate=16000,
        channels=1,
        silence_seconds=1.0,
        no_speech_seconds=5.0,
        min_speech_seconds=0.2,
        min_rms=0.0052,
        noise_multiplier=1.6,
        release_multiplier=1.35,
        calibration_seconds=0.25,
    )

    assert detector.feed(pcm_square_wave(900, 0.5)) is None
    assert detector.speech_detected is True
    assert 0.020 <= detector.trigger_threshold <= 0.021
    assert detector.feed(pcm_square_wave(360, 1.1)) == "silence"


def test_pi_voice_endpoint_detector_ignores_short_measured_noise_spikes():
    detector = server._PiVoiceEndpointDetector(
        rate=16000,
        channels=1,
        silence_seconds=1.0,
        no_speech_seconds=1.0,
        min_speech_seconds=0.2,
        min_rms=0.0052,
        noise_multiplier=1.6,
        release_multiplier=1.35,
        calibration_seconds=0.25,
    )

    assert detector.feed(pcm_square_wave(360, 0.25)) is None
    for _ in range(3):
        assert detector.feed(pcm_square_wave(650, 0.15)) is None
        assert detector.feed(pcm_square_wave(360, 0.05)) is None
    assert detector.speech_detected is False


def test_pi_voice_endpoint_detector_does_not_treat_measured_room_noise_as_speech():
    detector = server._PiVoiceEndpointDetector(
        rate=16000,
        channels=1,
        silence_seconds=1.0,
        no_speech_seconds=0.8,
        min_speech_seconds=0.2,
        min_rms=0.0052,
        noise_multiplier=1.6,
        release_multiplier=1.35,
        calibration_seconds=0.25,
    )

    assert detector.feed(pcm_square_wave(370, 0.9)) == "no_speech"
    assert detector.speech_detected is False
    assert detector.trigger_threshold > 0.017


def test_pi_record_vad_interrupts_arecord_and_finalizes_wav(monkeypatch, tmp_path):
    recorded_audio = tmp_path / "pi-record.wav"
    raw_audio = tmp_path / "pi-record.pcm"
    procs = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.command = command
            self.returncode = None
            self.sent_signal = None
            Path(command[-1]).write_bytes(
                pcm_square_wave(0, 0.3)
                + pcm_square_wave(5000, 0.3)
                + pcm_square_wave(0, 1.2)
            )
            procs.append(self)

        def poll(self):
            return self.returncode

        def send_signal(self, value):
            self.sent_signal = value
            self.returncode = -int(value)

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            if self.returncode is None:
                self.returncode = 0
            return "", ""

    monkeypatch.setattr(server, "_find_arecord", lambda: "/usr/bin/arecord")
    monkeypatch.setattr(server, "_pi_record_candidate_devices", lambda recorder: ["plughw:CARD=Device,DEV=0"])
    monkeypatch.setattr(server, "_create_pi_record_tempfile", lambda: recorded_audio)
    monkeypatch.setattr(server, "_create_pi_record_rawfile", lambda: raw_audio)
    monkeypatch.setattr(server.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(server.time, "sleep", lambda seconds: None)

    with server.PI_RECORD_LOCK:
        server.PI_RECORD_JOBS["vadjob"] = {"stop_requested": False, "proc": None}
    try:
        result = server._record_pi_audio(8, job_id="vadjob")
        with server.PI_RECORD_LOCK:
            job = dict(server.PI_RECORD_JOBS["vadjob"])
    finally:
        with server.PI_RECORD_LOCK:
            server.PI_RECORD_JOBS.pop("vadjob", None)

    assert result == recorded_audio
    assert procs[0].sent_signal == signal.SIGINT
    assert job["speech_detected"] is True
    assert job["endpoint_reason"] == "silence"
    assert job["vad_peak_rms"] > job["vad_trigger_threshold"]
    assert not raw_audio.exists()
    with wave.open(str(recorded_audio), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 16000
        assert 1.7 <= wav.getnframes() / wav.getframerate() <= 1.9


@pytest.mark.parametrize("duration", [2, 5])
@pytest.mark.parametrize("manual_stop", [False, True])
def test_pi_record_job_handles_silence_in_final_pcm_read(monkeypatch, tmp_path, duration, manual_stop):
    configure_tmp_app(monkeypatch, tmp_path)
    recorded_audio = tmp_path / "final-read.wav"
    raw_audio = tmp_path / "final-read.pcm"
    answered = []
    job_id = "final-read-job"

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.returncode = None
            self.polls = 0
            raw_audio.write_bytes(pcm_square_wave(0, duration - 0.1))

        def poll(self):
            self.polls += 1
            if self.polls == 2:
                with raw_audio.open("ab") as handle:
                    handle.write(pcm_square_wave(0, 0.1))
                if manual_stop:
                    with server.PI_RECORD_LOCK:
                        server.PI_RECORD_JOBS[job_id]["stop_requested"] = True
                self.returncode = 0
            return self.returncode

        def communicate(self, timeout=None):
            return "", ""

    def answer_audio(path, recorded_duration, session_id):
        answered.append(path)
        assert path.is_file()
        return {"reply": "manual stop reply", "transcript": "manual transcript"}

    monkeypatch.setattr(server, "PI_RECORD_VAD_ENABLED", True)
    monkeypatch.setattr(server, "PI_RECORD_VAD_NO_SPEECH_SECONDS", 5.0)
    monkeypatch.setattr(server, "PI_RECORD_RATE", 16000)
    monkeypatch.setattr(server, "PI_RECORD_CHANNELS", 1)
    monkeypatch.setattr(server, "_find_arecord", lambda: "/stub/arecord")
    monkeypatch.setattr(server, "_pi_record_candidate_devices", lambda recorder: ["stub"])
    monkeypatch.setattr(server, "_create_pi_record_tempfile", lambda: recorded_audio)
    monkeypatch.setattr(server, "_create_pi_record_rawfile", lambda: raw_audio)
    monkeypatch.setattr(server, "_answer_audio_path", answer_audio)
    monkeypatch.setattr(server.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(server.time, "sleep", lambda seconds: None)
    with server.PI_RECORD_LOCK:
        server.PI_RECORD_JOBS[job_id] = {
            "id": job_id,
            "duration": duration,
            "started_monotonic": server.time.monotonic(),
            "stop_requested": False,
        }

    server._run_pi_record_job(job_id)
    job = server._get_pi_record_job(job_id)

    assert job["speech_detected"] is False
    if manual_stop:
        assert job["endpoint_reason"] == "manual"
        assert job["status"] == "complete"
        assert answered == [recorded_audio]
    else:
        assert job["endpoint_reason"] == "no_speech"
        assert job["status"] == "error"
        assert job["status_code"] == 400
        assert job["error"] == "No speech was detected"
        assert answered == [], "Silent EOF must not reach STT, LLM, or TTS"
    assert not recorded_audio.exists()
    assert not raw_audio.exists()


def test_pi_record_endpoint_transcribes_and_cleans_audio(monkeypatch, tmp_path):
    client, audio_cache = configure_tmp_app(monkeypatch, tmp_path)
    reply_audio = audio_cache / "reply.ogg"
    reply_audio.write_bytes(b"OggS pi")
    recorded_audio = tmp_path / "pi-record.wav"
    recorded_audio.write_bytes(b"RIFF" + b"\0" * 64)

    monkeypatch.setattr(server, "_record_pi_audio", lambda duration: recorded_audio)
    monkeypatch.setattr(server, "_transcribe_audio", lambda path: {"success": True, "transcript": "树莓派录音测试"})
    monkeypatch.setattr(server, "_run_hermes", lambda prompt: "树莓派回复")
    monkeypatch.setattr(server, "_text_to_speech", lambda text: json.dumps({"file_path": str(reply_audio)}))

    response = client.post("/api/pi-record", json={"duration": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["duration"] == 5
    assert data["transcript"] == "树莓派录音测试"
    assert data["reply"] == "树莓派回复"
    assert data["audio_url"] == "/audio/reply.ogg"
    assert not recorded_audio.exists()


def test_pi_record_stop_endpoint_signals_running_job(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)

    class FakeProcess:
        def __init__(self):
            self.sent_signal = None

        def poll(self):
            return None

        def send_signal(self, value):
            self.sent_signal = value

    proc = FakeProcess()
    with server.PI_RECORD_LOCK:
        server.PI_RECORD_JOBS["job123"] = {
            "id": "job123",
            "status": "recording",
            "duration": 30,
            "elapsed": 0,
            "session_id": None,
            "started_at": server._now(),
            "started_monotonic": 1.0,
            "completed_at": None,
            "device": "plughw:CARD=Device,DEV=0",
            "stop_requested": False,
            "proc": proc,
            "audio_path": None,
            "result": None,
            "error": None,
            "status_code": None,
        }

    response = client.post("/api/pi-record/job123/stop")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "recording"
    assert data["stop_requested"] is True
    assert proc.sent_signal == signal.SIGINT
    with server.PI_RECORD_LOCK:
        assert server.PI_RECORD_JOBS["job123"]["stop_requested"] is True


def test_pi_record_honors_stop_requested_before_process_attaches(monkeypatch, tmp_path):
    recorded_audio = tmp_path / "pi-record.wav"
    raw_audio = tmp_path / "pi-record.pcm"
    procs = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.command = command
            self.returncode = 0
            self.sent_signal = None
            procs.append(self)

        def poll(self):
            return None if self.sent_signal is None else 0

        def send_signal(self, value):
            self.sent_signal = value

        def terminate(self):
            self.sent_signal = "terminate"

        def communicate(self, timeout=None):
            Path(self.command[-1]).write_bytes(b"\0\1" * 64)
            return "", ""

    monkeypatch.setattr(server, "_find_arecord", lambda: "/usr/bin/arecord")
    monkeypatch.setattr(server, "_pi_record_candidate_devices", lambda recorder: ["plughw:CARD=Device,DEV=0"])
    monkeypatch.setattr(server, "_create_pi_record_tempfile", lambda: recorded_audio)
    monkeypatch.setattr(server, "_create_pi_record_rawfile", lambda: raw_audio)
    monkeypatch.setattr(server.subprocess, "Popen", FakeProcess)

    with server.PI_RECORD_LOCK:
        server.PI_RECORD_JOBS["job456"] = {
            "id": "job456",
            "status": "recording",
            "duration": 30,
            "elapsed": 0,
            "session_id": None,
            "started_at": server._now(),
            "started_monotonic": 1.0,
            "completed_at": None,
            "device": None,
            "stop_requested": True,
            "proc": None,
            "audio_path": None,
            "result": None,
            "error": None,
            "status_code": None,
        }

    result = server._record_pi_audio(30, job_id="job456")

    assert result == recorded_audio
    assert procs[0].sent_signal == signal.SIGINT
    with server.PI_RECORD_LOCK:
        assert server.PI_RECORD_JOBS["job456"]["proc"] is None


def test_inline_local_stt_reuses_loaded_model(monkeypatch):
    class Segment:
        def __init__(self, text):
            self.text = text

    class Info:
        language = "zh"
        duration = 1.2

    class FakeModel:
        def __init__(self):
            self.calls = 0

        def transcribe(self, path, language=None, vad_filter=True):
            self.calls += 1
            assert path == "sample.wav"
            assert language == "zh"
            assert vad_filter is True
            return [Segment("你好"), Segment("世界")], Info()

    fake_model = FakeModel()
    monkeypatch.setattr(
        server,
        "_load_hermes_config",
        lambda: {
            "stt": {
                "enabled": True,
                "provider": "local",
                "local": {
                    "model": "base",
                    "language": "zh",
                    "device": "cpu",
                    "compute_type": "int8",
                },
            }
        },
    )
    monkeypatch.setattr(server, "_get_inline_local_stt_model", lambda options: fake_model)
    monkeypatch.setattr(
        server,
        "_transcribe_audio_subprocess",
        lambda path: (_ for _ in ()).throw(AssertionError("subprocess fallback should not run")),
    )

    result = server._transcribe_audio("sample.wav")

    assert result["success"] is True
    assert result["transcript"] == "你好世界"
    assert result["runtime"] == "inline-cache"
    assert fake_model.calls == 1


def test_local_stt_status_requires_real_model_file(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_load_hermes_config", lambda: {"stt": {"enabled": True, "provider": "local", "local": {"model": "base"}}})
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setattr(server, "MIN_LOCAL_STT_MODEL_BYTES", 10)

    snapshot = tmp_path / "hf" / "hub" / "models--Systran--faster-whisper-base" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    model = snapshot / "model.bin"
    model.write_bytes(b"tiny")

    assert server._stt_status()["ready"] is False

    model.write_bytes(b"0123456789")
    status = server._stt_status()
    assert status["ready"] is True
    assert status["local_model_cached"] is True
    assert status["local_model_bytes"] == 10


def test_audio_route_rejects_traversal(monkeypatch, tmp_path):
    client, _ = configure_tmp_app(monkeypatch, tmp_path)
    response = client.get("/audio/%2e%2e/%2e%2e/etc/passwd")
    assert response.status_code == 404
    assert response.json()["detail"] == "not found"
