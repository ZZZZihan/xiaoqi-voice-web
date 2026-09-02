from __future__ import annotations

import json
import importlib
import asyncio
import gzip
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, unquote, urlparse
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse


HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
HERMES_AGENT = Path(os.environ.get("HERMES_AGENT", HERMES_HOME / "hermes-agent")).expanduser()
AUDIO_CACHE = HERMES_HOME / "audio_cache"
UPLOAD_DIR = HERMES_HOME / "voice_web_uploads"
SESSIONS_FILE = HERMES_HOME / "voice-web" / "sessions.json"
REMINDERS_FILE = HERMES_HOME / "voice-web" / "reminders.json"
INDEX_FILE = Path(__file__).with_name("index.html")
CALL_MODE_FILE = Path(__file__).with_name("call-mode.js")
APP_CSS_FILE = Path(__file__).with_name("app.css")
UI_MOTION_FILE = Path(__file__).with_name("ui-motion.js")
HERMES_TIMEOUT = int(os.environ.get("VOICE_WEB_HERMES_TIMEOUT", "300"))
STT_TIMEOUT = int(os.environ.get("VOICE_WEB_STT_TIMEOUT", "180"))
MAX_MESSAGE_CHARS = int(os.environ.get("VOICE_WEB_MAX_MESSAGE_CHARS", "12000"))
MAX_HISTORY_MESSAGES = int(os.environ.get("VOICE_WEB_MAX_HISTORY_MESSAGES", "18"))
MAX_SESSIONS = int(os.environ.get("VOICE_WEB_MAX_SESSIONS", "100"))
MAX_REMINDERS = int(os.environ.get("VOICE_WEB_MAX_REMINDERS", "200"))
MIN_LOCAL_STT_MODEL_BYTES = int(os.environ.get("VOICE_WEB_MIN_LOCAL_STT_MODEL_BYTES", str(25 * 1024 * 1024)))
WEATHER_DEFAULT_LOCATION = os.environ.get("VOICE_WEB_DEFAULT_WEATHER_LOCATION", "").strip()
WEATHER_TIMEOUT = float(os.environ.get("VOICE_WEB_WEATHER_TIMEOUT", "8"))
PI_RECORD_DEVICE = os.environ.get("VOICE_WEB_PI_RECORD_DEVICE", "").strip()
PI_RECORD_RATE = int(os.environ.get("VOICE_WEB_PI_RECORD_RATE", "16000"))
PI_RECORD_CHANNELS = int(os.environ.get("VOICE_WEB_PI_RECORD_CHANNELS", "1"))
PI_PLAYBACK_COMMAND = os.environ.get("VOICE_WEB_PI_PLAYBACK_COMMAND", "").strip()
PI_PLAYBACK_DEVICE = os.environ.get("VOICE_WEB_PI_PLAYBACK_DEVICE", "").strip()
PI_PLAYBACK_TIMEOUT = int(os.environ.get("VOICE_WEB_PI_PLAYBACK_TIMEOUT", "180"))
HERMES_MAX_TURNS = max(1, int(os.environ.get("VOICE_WEB_HERMES_MAX_TURNS", "3")))
VOLCENGINE_ASR_API_VERSION = os.environ.get("VOLCENGINE_ASR_API_VERSION", "v2").strip().lower()
VOLCENGINE_ASR_V2_WS_URL = os.environ.get(
    "VOLCENGINE_ASR_V2_WS_URL",
    "wss://openspeech.bytedance.com/api/v2/asr",
).strip()
VOLCENGINE_ASR_WS_URL = os.environ.get(
    "VOLCENGINE_ASR_WS_URL",
    "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream",
).strip()
VOLCENGINE_ASR_SUBMIT_URL = os.environ.get(
    "VOLCENGINE_ASR_SUBMIT_URL",
    "https://openspeech.bytedance.com/api/v1/auc/submit",
).strip()
VOLCENGINE_ASR_QUERY_URL = os.environ.get(
    "VOLCENGINE_ASR_QUERY_URL",
    "https://openspeech.bytedance.com/api/v1/auc/query",
).strip()
VOLCENGINE_ASR_RESOURCE_ID = os.environ.get("VOLCENGINE_ASR_RESOURCE_ID", "volc.bigasr.sauc.duration").strip()
DIRECT_HERMES_VOICE = os.environ.get("VOICE_WEB_DIRECT_HERMES_VOICE", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
ASSISTANT_NAME = os.environ.get("VOICE_WEB_ASSISTANT_NAME", "生活助手小七").strip() or "生活助手小七"
USER_NAME = os.environ.get("VOICE_WEB_USER_NAME", "Soul").strip() or "Soul"
USER_PROFILE = (
    os.environ.get("VOICE_WEB_USER_PROFILE", "学生，需要你帮助完成学习上的事情，也可以协助日常安排。").strip()
    or "学生，需要你帮助完成学习上的事情，也可以协助日常安排。"
)
COMMAND_DENIED_REPLY = (
    "我这边不能在语音网页里执行需要审批的命令，所以刚才没有拿到可靠的实时结果。"
    "如果你需要实时天气，请直接告诉我要查的城市，比如“查天津天气”，我会走内置天气查询。"
)
COMMAND_DENIED_MARKERS = (
    "DANGEROUS COMMAND",
    "script execution via -e/-c flag",
    "Choice [o/s/a/D]",
    "✗ Denied",
)
HERMES_RUNTIME_NOTICE_MARKERS = (
    "Reached maximum iterations",
    "Requesting summary",
    "tirith security scanner enabled but not available",
)
WEATHER_QUERY_MARKERS = (
    "天气",
    "气温",
    "温度",
    "降雨",
    "降水",
    "下雨",
    "下雪",
    "雨伞",
    "带伞",
    "热不热",
    "冷不冷",
    "穿什么",
    "空气湿度",
    "风大",
)
BRIEFING_QUERY_MARKERS = (
    "今日简报",
    "每日简报",
    "早间简报",
    "早安",
    "早上好",
    "今天怎么样",
    "今天安排",
    "今天有什么",
    "播报一下",
    "来个简报",
    "给我简报",
)
REMINDER_CREATE_MARKERS = (
    "提醒我",
    "帮我提醒",
    "记得提醒我",
    "记一下",
    "帮我记一下",
    "加入待办",
    "添加待办",
    "加个待办",
    "新增待办",
)
REMINDER_LIST_MARKERS = (
    "我的提醒",
    "提醒列表",
    "待办列表",
    "我的待办",
    "有什么提醒",
    "有哪些提醒",
    "还有什么事",
    "今天的提醒",
    "今天待办",
)
REMINDER_DONE_MARKERS = (
    "完成提醒",
    "完成待办",
    "提醒完成",
    "待办完成",
    "已经完成",
    "搞定提醒",
    "搞定待办",
)
WEATHER_CODE_DESCRIPTIONS = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "较强毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹",
}

SESSION_LOCK = threading.Lock()
REMINDERS_LOCK = threading.Lock()
PI_RECORD_LOCK = threading.Lock()
LOCAL_STT_LOCK = threading.Lock()
PI_RECORD_JOBS: dict[str, dict[str, Any]] = {}
MAX_PI_RECORD_JOBS = 20
LOCAL_STT_MODEL_CACHE: dict[tuple[str, str | None, str, str, int | None], Any] = {}
LOCAL_STT_PRELOAD_ERROR: str | None = None


app = FastAPI(title="Hermes Voice Web")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _compact_text(value: Any, limit: int = MAX_MESSAGE_CHARS) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _title_from_text(text: str) -> str:
    title = _compact_text(text, 32)
    return title or "新会话"


def _new_session(title: str | None = None) -> dict[str, Any]:
    now = _now()
    return {
        "id": uuid4().hex[:12],
        "title": _title_from_text(title or "新会话"),
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


def _normalise_message(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None

    role = str(message.get("role") or "").strip()
    if role not in {"user", "assistant"}:
        return None

    content = str(message.get("content") or "").strip()
    if not content:
        return None
    if _looks_like_denied_command_output(content):
        content = COMMAND_DENIED_REPLY
    elif role == "assistant":
        content = _clean_reply(content)
        if not content:
            return None

    normalised = {
        "id": str(message.get("id") or uuid4().hex[:12]),
        "role": role,
        "content": content,
        "kind": str(message.get("kind") or "text"),
        "created_at": str(message.get("created_at") or _now()),
    }
    for key in ("audio_url", "duration", "tts"):
        if key in message and message[key] not in (None, ""):
            normalised[key] = message[key]
    return normalised


def _normalise_session(session: Any) -> dict[str, Any] | None:
    if not isinstance(session, dict):
        return None

    session_id = str(session.get("id") or "").strip()
    if not session_id:
        return None

    messages = []
    for message in session.get("messages") or []:
        normalised = _normalise_message(message)
        if normalised:
            messages.append(normalised)

    now = _now()
    return {
        "id": session_id,
        "title": _title_from_text(session.get("title") or "新会话"),
        "created_at": str(session.get("created_at") or now),
        "updated_at": str(session.get("updated_at") or session.get("created_at") or now),
        "messages": messages,
    }


def _read_sessions_unlocked() -> dict[str, Any]:
    if not SESSIONS_FILE.exists():
        return {"sessions": []}

    try:
        raw = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sessions": []}

    sessions = []
    for session in raw.get("sessions") or []:
        normalised = _normalise_session(session)
        if normalised:
            sessions.append(normalised)
    sessions.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return {"sessions": sessions[:MAX_SESSIONS]}


def _write_sessions_unlocked(data: dict[str, Any]) -> None:
    sessions = data.get("sessions") or []
    sessions.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSIONS_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"sessions": sessions[:MAX_SESSIONS]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(SESSIONS_FILE)


def _copy_session(session: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(session, ensure_ascii=False))


def _session_summary(session: dict[str, Any]) -> dict[str, Any]:
    messages = session.get("messages") or []
    last = messages[-1] if messages else {}
    return {
        "id": session["id"],
        "title": session.get("title") or "新会话",
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "message_count": len(messages),
        "last_message": _compact_text(last.get("content"), 72) if last else "",
    }


def _list_sessions() -> list[dict[str, Any]]:
    with SESSION_LOCK:
        data = _read_sessions_unlocked()
        return [_session_summary(session) for session in data["sessions"]]


def _create_session(title: str | None = None) -> dict[str, Any]:
    with SESSION_LOCK:
        data = _read_sessions_unlocked()
        session = _new_session(title)
        data["sessions"].insert(0, session)
        _write_sessions_unlocked(data)
        return _copy_session(session)


def _find_session_unlocked(data: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    for session in data.get("sessions") or []:
        if session.get("id") == session_id:
            return session
    return None


def _get_session(session_id: str) -> dict[str, Any]:
    with SESSION_LOCK:
        data = _read_sessions_unlocked()
        session = _find_session_unlocked(data, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return _copy_session(session)


def _prepare_session(session_id: str | None = None) -> dict[str, Any]:
    if not session_id:
        return _create_session()

    with SESSION_LOCK:
        data = _read_sessions_unlocked()
        session = _find_session_unlocked(data, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return _copy_session(session)


def _rename_session(session_id: str, title: str) -> dict[str, Any]:
    title = _title_from_text(title)
    with SESSION_LOCK:
        data = _read_sessions_unlocked()
        session = _find_session_unlocked(data, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        session["title"] = title
        session["updated_at"] = _now()
        _write_sessions_unlocked(data)
        return _copy_session(session)


def _delete_session(session_id: str) -> None:
    with SESSION_LOCK:
        data = _read_sessions_unlocked()
        before = len(data.get("sessions") or [])
        data["sessions"] = [session for session in data.get("sessions") or [] if session.get("id") != session_id]
        if len(data["sessions"]) == before:
            raise HTTPException(status_code=404, detail="Session not found")
        _write_sessions_unlocked(data)


def _append_exchange(
    session_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    title_seed: str,
) -> dict[str, Any]:
    with SESSION_LOCK:
        data = _read_sessions_unlocked()
        session = _find_session_unlocked(data, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if not session.get("messages") and session.get("title") == "新会话":
            session["title"] = _title_from_text(title_seed)

        now = _now()
        session.setdefault("messages", []).extend([user_message, assistant_message])
        session["updated_at"] = now
        _write_sessions_unlocked(data)
        return _copy_session(session)


def _normalise_reminder(reminder: Any) -> dict[str, Any] | None:
    if not isinstance(reminder, dict):
        return None

    text = str(reminder.get("text") or "").strip()
    if not text:
        return None

    now = _now()
    done = reminder.get("done")
    if isinstance(done, str):
        done = done.strip().lower() in {"1", "true", "yes", "on", "done", "complete", "completed"}
    return {
        "id": str(reminder.get("id") or uuid4().hex[:12]),
        "text": _compact_text(text, 240),
        "due_at": str(reminder.get("due_at") or "").strip() or None,
        "due_text": _compact_text(reminder.get("due_text"), 80) or None,
        "due_precision": str(reminder.get("due_precision") or "").strip() or None,
        "created_at": str(reminder.get("created_at") or now),
        "updated_at": str(reminder.get("updated_at") or now),
        "done": bool(done),
        "completed_at": str(reminder.get("completed_at") or "").strip() or None,
    }


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "done", "complete", "completed"}


def _reminder_sort_key(reminder: dict[str, Any]) -> tuple[Any, ...]:
    due_at = reminder.get("due_at") or "9999-12-31T23:59:59"
    return (
        bool(reminder.get("done")),
        due_at,
        reminder.get("created_at") or "",
        reminder.get("id") or "",
    )


def _read_reminders_unlocked() -> dict[str, Any]:
    if not REMINDERS_FILE.exists():
        return {"reminders": []}

    try:
        raw = json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"reminders": []}

    reminders = []
    for reminder in raw.get("reminders") or []:
        normalised = _normalise_reminder(reminder)
        if normalised:
            reminders.append(normalised)
    reminders.sort(key=_reminder_sort_key)
    return {"reminders": reminders[:MAX_REMINDERS]}


def _write_reminders_unlocked(data: dict[str, Any]) -> None:
    reminders = []
    for reminder in data.get("reminders") or []:
        normalised = _normalise_reminder(reminder)
        if normalised:
            reminders.append(normalised)
    reminders.sort(key=_reminder_sort_key)
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REMINDERS_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"reminders": reminders[:MAX_REMINDERS]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(REMINDERS_FILE)


def _list_reminders(include_done: bool = False) -> list[dict[str, Any]]:
    with REMINDERS_LOCK:
        reminders = _read_reminders_unlocked()["reminders"]
        if include_done:
            return json.loads(json.dumps(reminders, ensure_ascii=False))
        return json.loads(json.dumps([item for item in reminders if not item.get("done")], ensure_ascii=False))


def _find_reminder_unlocked(data: dict[str, Any], reminder_id: str) -> dict[str, Any] | None:
    for reminder in data.get("reminders") or []:
        if reminder.get("id") == reminder_id:
            return reminder
    return None


def _create_reminder(
    text: str,
    *,
    due_at: str | None = None,
    due_text: str | None = None,
    due_precision: str | None = None,
) -> dict[str, Any]:
    text = _compact_text(text, 240)
    if not text:
        raise HTTPException(status_code=400, detail="Reminder text is empty")

    now = _now()
    reminder = {
        "id": uuid4().hex[:12],
        "text": text,
        "due_at": str(due_at or "").strip() or None,
        "due_text": _compact_text(due_text, 80) or None,
        "due_precision": str(due_precision or "").strip() or None,
        "created_at": now,
        "updated_at": now,
        "done": False,
        "completed_at": None,
    }
    with REMINDERS_LOCK:
        data = _read_reminders_unlocked()
        data["reminders"].append(reminder)
        _write_reminders_unlocked(data)
    return reminder


def _update_reminder(reminder_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    with REMINDERS_LOCK:
        data = _read_reminders_unlocked()
        reminder = _find_reminder_unlocked(data, reminder_id)
        if not reminder:
            raise HTTPException(status_code=404, detail="Reminder not found")

        if "text" in updates:
            text = _compact_text(updates.get("text"), 240)
            if not text:
                raise HTTPException(status_code=400, detail="Reminder text is empty")
            reminder["text"] = text
        if "due_at" in updates:
            reminder["due_at"] = str(updates.get("due_at") or "").strip() or None
        if "due_text" in updates:
            reminder["due_text"] = _compact_text(updates.get("due_text"), 80) or None
        if "due_precision" in updates:
            reminder["due_precision"] = str(updates.get("due_precision") or "").strip() or None
        if "done" in updates:
            done = _coerce_bool(updates.get("done"))
            reminder["done"] = done
            reminder["completed_at"] = _now() if done else None
        reminder["updated_at"] = _now()
        _write_reminders_unlocked(data)
        return json.loads(json.dumps(reminder, ensure_ascii=False))


def _delete_reminder(reminder_id: str) -> None:
    with REMINDERS_LOCK:
        data = _read_reminders_unlocked()
        before = len(data.get("reminders") or [])
        data["reminders"] = [item for item in data.get("reminders") or [] if item.get("id") != reminder_id]
        if len(data["reminders"]) == before:
            raise HTTPException(status_code=404, detail="Reminder not found")
        _write_reminders_unlocked(data)


CHINESE_NUMBER_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _chinese_number_to_int(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    text = text.replace("〇", "零")
    if text in CHINESE_NUMBER_DIGITS:
        return CHINESE_NUMBER_DIGITS[text]
    if text == "十":
        return 10
    if "十" in text:
        left, right = text.split("十", 1)
        tens = 1 if not left else CHINESE_NUMBER_DIGITS.get(left)
        ones = 0 if not right else CHINESE_NUMBER_DIGITS.get(right)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return None


def _parse_reminder_due(text: str) -> dict[str, str | None]:
    raw = str(text or "")
    now = datetime.now().astimezone()
    due_date = None
    date_label = None

    if "后天" in raw:
        due_date = now.date() + timedelta(days=2)
        date_label = "后天"
    elif "明天" in raw:
        due_date = now.date() + timedelta(days=1)
        date_label = "明天"
    elif "今天" in raw or "今晚" in raw:
        due_date = now.date()
        date_label = "今天"
    else:
        date_match = re.search(
            r"(?:(20\d{2})\s*[年/-]\s*)?(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*(?:日|号)?",
            raw,
        )
        if date_match:
            year = int(date_match.group(1) or now.year)
            month = int(date_match.group(2))
            day = int(date_match.group(3))
            try:
                due_date = datetime(year, month, day, tzinfo=now.tzinfo).date()
                if not date_match.group(1) and due_date < now.date():
                    due_date = datetime(year + 1, month, day, tzinfo=now.tzinfo).date()
                date_label = due_date.isoformat()
            except ValueError:
                due_date = None

    time_match = re.search(
        r"(?P<period>凌晨|早上|上午|中午|下午|晚上|今晚|夜里)?\s*"
        r"(?P<hour>[0-2]?\d|[零〇一二两三四五六七八九十]{1,3})"
        r"(?:[:：点时](?P<minute>[0-5]?\d|半|[零〇一二两三四五六七八九十]{1,3})?)",
        raw,
    )
    hour = None
    minute = 0
    time_label = None
    if time_match:
        hour = _chinese_number_to_int(time_match.group("hour"))
        minute_token = time_match.group("minute")
        if minute_token:
            minute = 30 if minute_token == "半" else _chinese_number_to_int(minute_token) or 0
        period = time_match.group("period") or ""
        if hour is not None:
            if period in {"下午", "晚上", "今晚", "夜里"} and hour < 12:
                hour += 12
            elif period == "中午" and hour < 11:
                hour += 12
            elif period == "凌晨" and hour == 12:
                hour = 0
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                hour = None
        if hour is not None:
            time_label = f"{hour:02d}:{minute:02d}"

    if not due_date and hour is not None:
        due_date = now.date()
        candidate = datetime.combine(due_date, datetime.min.time(), tzinfo=now.tzinfo).replace(hour=hour, minute=minute)
        if candidate <= now:
            due_date = due_date + timedelta(days=1)
        date_label = due_date.isoformat()

    if not due_date:
        return {"due_at": None, "due_text": None, "due_precision": None}

    precision = "datetime" if hour is not None else "date"
    hour = 9 if hour is None else hour
    minute = 0 if precision == "date" else minute
    due_dt = datetime.combine(due_date, datetime.min.time(), tzinfo=now.tzinfo).replace(hour=hour, minute=minute)
    due_text = " ".join(part for part in (date_label, time_label) if part)
    return {
        "due_at": due_dt.isoformat(timespec="minutes"),
        "due_text": due_text or due_date.isoformat(),
        "due_precision": precision,
    }


def _strip_reminder_due_prefix(text: str, due: dict[str, str | None]) -> str:
    cleaned = str(text or "").strip(" ：:，,。.")
    if due.get("due_at"):
        cleaned = re.sub(
            r"^(?:今天|明天|后天|今晚|(?:(?:20\d{2})\s*[年/-]\s*)?\d{1,2}\s*[月/-]\s*\d{1,2}\s*(?:日|号)?)\s*",
            "",
            cleaned,
            count=1,
        )
        if due.get("due_precision") == "datetime":
            cleaned = re.sub(
                r"^(?:凌晨|早上|上午|中午|下午|晚上|今晚|夜里)?\s*"
                r"(?:[0-2]?\d|[零〇一二两三四五六七八九十]{1,3})"
                r"(?:[:：点时](?:[0-5]?\d|半|[零〇一二两三四五六七八九十]{1,3})?)\s*(?:分)?\s*"
                r"(?:左右|之前|前|的时候)?\s*",
                "",
                cleaned,
                count=1,
            )
    cleaned = re.sub(r"^(要|记得|帮我|提醒我)\s*", "", cleaned)
    return cleaned.strip(" ：:，,。.")


def _extract_reminder_create_payload(text: str) -> dict[str, str | None] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    patterns = [
        r"^(?:请|麻烦你?|小七)?\s*(?:提醒我|帮我提醒|记得提醒我)\s*[:：，,]?\s*(.+)$",
        r"^(?:请|麻烦你?|小七)?\s*(?:记一下|帮我记一下)\s*[:：，,]?\s*(.+)$",
        r"^(?:请|麻烦你?|小七)?\s*(?:加入待办|添加待办|加个待办|新增待办)\s*[:：，,]?\s*(.+)$",
    ]
    body = None
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            body = match.group(1).strip()
            break
    if body is None:
        compact = re.sub(r"\s+", "", raw)
        if not any(marker in compact for marker in REMINDER_CREATE_MARKERS):
            return None
        body = raw
        for marker in REMINDER_CREATE_MARKERS:
            body = body.replace(marker, " ", 1)
        body = body.strip(" ：:，,。.")

    due = _parse_reminder_due(body)
    reminder_text = _strip_reminder_due_prefix(body, due)
    if not reminder_text:
        reminder_text = body.strip(" ：:，,。.")
    return {
        "text": reminder_text,
        "due_at": due["due_at"],
        "due_text": due["due_text"],
        "due_precision": due["due_precision"],
    }


def _format_reminder_due(reminder: dict[str, Any]) -> str:
    due_text = reminder.get("due_text")
    due_at = reminder.get("due_at")
    if due_at:
        try:
            parsed = datetime.fromisoformat(str(due_at).replace("Z", "+00:00")).astimezone()
            if reminder.get("due_precision") == "date":
                return str(due_text or parsed.date().isoformat())
            return str(due_text or parsed.strftime("%Y-%m-%d %H:%M"))
        except ValueError:
            pass
    return str(due_text or "未定时间")


def _format_reminder_list_reply(reminders: list[dict[str, Any]]) -> str:
    if not reminders:
        return "现在没有未完成提醒。"
    lines = [f"你现在有 {len(reminders)} 个未完成提醒："]
    for index, reminder in enumerate(reminders[:8], start=1):
        lines.append(f"{index}. {reminder['text']}（{_format_reminder_due(reminder)}）")
    if len(reminders) > 8:
        lines.append(f"还有 {len(reminders) - 8} 个稍后再看。")
    return "\n".join(lines)


def _format_reminders_context(reminders: list[dict[str, Any]] | None = None) -> str:
    reminders = reminders if reminders is not None else _list_reminders(include_done=False)
    lines = ["REMINDER_CONTEXT:"]
    if not reminders:
        lines.append("暂无未完成提醒。")
        return "\n".join(lines)
    lines.append(f"未完成提醒共 {len(reminders)} 条，优先关注近期和未定时间事项。")
    for reminder in reminders[:10]:
        lines.append(f"- {reminder['text']}（时间：{_format_reminder_due(reminder)}；id：{reminder['id']}）")
    return "\n".join(lines)


def _is_reminder_list_query(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return any(marker in compact for marker in REMINDER_LIST_MARKERS)


def _is_reminder_done_query(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return any(marker in compact for marker in REMINDER_DONE_MARKERS)


def _extract_reminder_done_text(text: str) -> str:
    raw = str(text or "").strip()
    for marker in REMINDER_DONE_MARKERS:
        raw = raw.replace(marker, " ", 1)
    raw = raw.replace("这个", " ").replace("这条", " ").replace("那条", " ")
    return re.sub(r"\s+", " ", raw).strip(" ：:，,。.")


def _complete_matching_reminder(query: str) -> str:
    reminders = _list_reminders(include_done=False)
    if not reminders:
        return "现在没有未完成提醒。"

    query = _compact_text(query, 120)
    target = None
    if not query:
        if len(reminders) == 1:
            target = reminders[0]
        else:
            return "你有多个未完成提醒。请说“完成提醒 + 事项关键词”，我再帮你标记。"
    else:
        for reminder in reminders:
            text = str(reminder.get("text") or "")
            if query == reminder.get("id") or query in text or text in query:
                target = reminder
                break
    if not target:
        return "我没找到匹配的未完成提醒。你可以说“我的提醒”先看列表。"

    updated = _update_reminder(target["id"], {"done": True})
    return f"已标记完成：{updated['text']}。"


def _handle_reminder_intent(user_text: str) -> str | None:
    payload = _extract_reminder_create_payload(user_text)
    if payload:
        if not payload["text"]:
            return "要提醒什么？你可以说“提醒我明天上午九点交作业”。"
        reminder = _create_reminder(
            payload["text"] or "",
            due_at=payload["due_at"],
            due_text=payload["due_text"],
            due_precision=payload["due_precision"],
        )
        return f"已记下本地提醒：{reminder['text']}（{_format_reminder_due(reminder)}）。我会在提醒列表和今日简报里带上它。"

    if _is_reminder_done_query(user_text):
        return _complete_matching_reminder(_extract_reminder_done_text(user_text))

    if _is_reminder_list_query(user_text):
        return _format_reminder_list_reply(_list_reminders(include_done=False))

    return None


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _agent_tool_status() -> dict[str, bool]:
    return {
        "transcription_tools": (HERMES_AGENT / "tools" / "transcription_tools.py").exists(),
        "tts_tool": (HERMES_AGENT / "tools" / "tts_tool.py").exists(),
    }


def _load_hermes_config() -> dict[str, Any]:
    if not HERMES_AGENT.exists():
        return {}

    agent_path = str(HERMES_AGENT)
    if agent_path not in sys.path:
        sys.path.insert(0, agent_path)

    try:
        from hermes_cli.config import load_config

        return load_config()
    except Exception:
        return {}


def _is_enabled(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _cached_local_stt_model_file(model: str) -> Path | None:
    cache_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")).expanduser()
    model_cache = cache_home / "hub" / f"models--Systran--faster-whisper-{model}"
    model_files = list(model_cache.glob("snapshots/*/model.bin"))
    return next((path for path in model_files if path.exists()), None)


def _local_stt_options(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else _load_hermes_config()
    stt_config = config.get("stt", {}) if isinstance(config.get("stt"), dict) else {}
    local_config = stt_config.get("local", {}) if isinstance(stt_config.get("local"), dict) else {}
    model = str(local_config.get("model") or "base")
    cached_model = _cached_local_stt_model_file(model)
    cpu_threads = local_config.get("cpu_threads") or os.environ.get("HERMES_LOCAL_STT_CPU_THREADS")
    try:
        cpu_threads = int(cpu_threads) if cpu_threads not in (None, "") else None
    except (TypeError, ValueError):
        cpu_threads = None
    return {
        "enabled": _is_enabled(stt_config.get("enabled"), default=True),
        "provider": str(stt_config.get("provider") or "local"),
        "model": model,
        "model_path": str(cached_model.parent) if cached_model else None,
        "language": str(local_config.get("language") or os.environ.get("HERMES_LOCAL_STT_LANGUAGE") or "auto"),
        "device": str(local_config.get("device") or os.environ.get("HERMES_LOCAL_STT_DEVICE") or "cpu"),
        "compute_type": str(local_config.get("compute_type") or os.environ.get("HERMES_LOCAL_STT_COMPUTE_TYPE") or "int8"),
        "cpu_threads": cpu_threads,
        "vad_filter": _is_enabled(local_config.get("vad_filter"), default=True),
    }


def _volcengine_stt_options(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else _load_hermes_config()
    stt_config = config.get("stt", {}) if isinstance(config.get("stt"), dict) else {}
    volc_config = stt_config.get("volcengine", {}) if isinstance(stt_config.get("volcengine"), dict) else {}
    app_key = (
        volc_config.get("app_key")
        or volc_config.get("app_id")
        or os.environ.get("VOLCENGINE_ASR_APP_KEY")
        or os.environ.get("VOLCENGINE_ASR_APP_ID")
        or os.environ.get("VOLCENGINE_APP_KEY")
        or os.environ.get("VOLCENGINE_APP_ID")
        or ""
    )
    access_key = (
        volc_config.get("access_key")
        or volc_config.get("access_token")
        or volc_config.get("token")
        or os.environ.get("VOLCENGINE_ASR_ACCESS_TOKEN")
        or os.environ.get("VOLCENGINE_ASR_ACCESS_KEY")
        or os.environ.get("VOLCENGINE_ASR_TOKEN")
        or os.environ.get("VOLCENGINE_ACCESS_KEY")
        or os.environ.get("VOLCENGINE_ACCESS_TOKEN")
        or os.environ.get("VOLCENGINE_TOKEN")
        or ""
    )
    secret_key = (
        volc_config.get("secret_key")
        or volc_config.get("access_secret")
        or volc_config.get("secret")
        or os.environ.get("VOLCENGINE_ASR_SECRET_KEY")
        or os.environ.get("VOLCENGINE_ASR_ACCESS_SECRET")
        or os.environ.get("VOLCENGINE_SECRET_KEY")
        or os.environ.get("VOLCENGINE_ACCESS_SECRET")
        or ""
    )
    api_version = str(volc_config.get("api_version") or VOLCENGINE_ASR_API_VERSION or "v2").strip().lower()
    cluster = (
        volc_config.get("cluster")
        or os.environ.get("VOLCENGINE_ASR_CLUSTER")
        or os.environ.get("VOLCENGINE_CLUSTER")
        or ""
    )
    audio_base_url = (
        volc_config.get("audio_base_url")
        or os.environ.get("VOICE_WEB_PUBLIC_BASE_URL")
        or os.environ.get("VOLCENGINE_ASR_AUDIO_BASE_URL")
        or ""
    )
    return {
        "app_key": str(app_key).strip(),
        "access_key": str(access_key).strip(),
        "secret_key": str(secret_key).strip(),
        "api_version": api_version,
        "cluster": str(cluster).strip(),
        "audio_base_url": str(audio_base_url).strip().rstrip("/"),
        "v2_ws_url": str(volc_config.get("v2_ws_url") or VOLCENGINE_ASR_V2_WS_URL).strip(),
        "ws_url": str(volc_config.get("ws_url") or VOLCENGINE_ASR_WS_URL).strip(),
        "submit_url": str(volc_config.get("submit_url") or VOLCENGINE_ASR_SUBMIT_URL).strip(),
        "query_url": str(volc_config.get("query_url") or VOLCENGINE_ASR_QUERY_URL).strip(),
        "resource_id": str(volc_config.get("resource_id") or VOLCENGINE_ASR_RESOURCE_ID).strip(),
        "language": str(volc_config.get("language") or "zh-CN").strip(),
        "audio_format": str(volc_config.get("audio_format") or "").strip().lower(),
        "chunk_size": max(1024, int(volc_config.get("chunk_size") or os.environ.get("VOLCENGINE_ASR_CHUNK_SIZE", "32000"))),
        "seg_duration_ms": max(1000, int(volc_config.get("seg_duration_ms") or os.environ.get("VOLCENGINE_ASR_SEG_DURATION_MS", "15000"))),
        "workflow": str(
            volc_config.get("workflow")
            or os.environ.get("VOLCENGINE_ASR_WORKFLOW")
            or "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate"
        ).strip(),
        "result_type": str(volc_config.get("result_type") or os.environ.get("VOLCENGINE_ASR_RESULT_TYPE") or "full").strip(),
        "poll_interval": float(volc_config.get("poll_interval") or 1.0),
        "timeout": float(volc_config.get("timeout") or STT_TIMEOUT),
    }


def _inline_local_stt_enabled() -> bool:
    return _is_enabled(os.environ.get("VOICE_WEB_INLINE_LOCAL_STT"), default=True)


def _preload_local_stt_enabled() -> bool:
    return _is_enabled(os.environ.get("VOICE_WEB_PRELOAD_LOCAL_STT"), default=True)


def _should_use_inline_local_stt(config: dict[str, Any] | None = None) -> bool:
    options = _local_stt_options(config)
    return bool(options["enabled"] and options["provider"] == "local" and _inline_local_stt_enabled())


def _local_stt_cache_key(options: dict[str, Any]) -> tuple[str, str | None, str, str, int | None]:
    return (
        str(options["model"]),
        str(options["model_path"]) if options.get("model_path") else None,
        str(options["device"]),
        str(options["compute_type"]),
        options.get("cpu_threads") if isinstance(options.get("cpu_threads"), int) else None,
    )


def _local_stt_model_loaded(options: dict[str, Any]) -> bool:
    return _local_stt_cache_key(options) in LOCAL_STT_MODEL_CACHE


def _volcengine_missing_fields(options: dict[str, Any]) -> list[str]:
    required: list[tuple[str, Any]] = [
        ("app_key", options["app_key"]),
        ("access_key", options["access_key"]),
    ]
    if options.get("api_version") == "v2":
        required.extend(
            [
                ("cluster", options["cluster"]),
                ("v2_ws_url", options["v2_ws_url"]),
            ]
        )
    else:
        required.extend(
            [
                ("ws_url", options["ws_url"]),
                ("resource_id", options["resource_id"]),
            ]
        )
    return [name for name, value in required if not value]


def _stt_status() -> dict[str, Any]:
    config = _load_hermes_config()
    stt_config = config.get("stt", {}) if isinstance(config, dict) else {}
    enabled = _is_enabled(stt_config.get("enabled"), default=True)
    provider = str(stt_config.get("provider") or "local")

    status: dict[str, Any] = {
        "enabled": enabled,
        "provider": provider,
        "ready": False,
    }
    if not enabled or provider == "none":
        status["ready"] = False
        return status

    if provider == "local":
        local_options = _local_stt_options(config)
        model = str(local_options["model"])
        language = str(local_options["language"])
        model_file = _cached_local_stt_model_file(model)
        model_size = model_file.stat().st_size if model_file else 0
        model_ready = model_size >= MIN_LOCAL_STT_MODEL_BYTES
        status.update(
            {
                "local_model": model,
                "language": language,
                "local_model_cached": model_ready,
                "local_model_file": str(model_file) if model_file else None,
                "local_model_path": local_options.get("model_path"),
                "local_model_bytes": model_size,
                "ready": model_ready,
                "runtime": "inline-cache" if _should_use_inline_local_stt(config) else "subprocess",
                "model_loaded": _local_stt_model_loaded(local_options),
                "preload_enabled": _preload_local_stt_enabled(),
                "preload_error": LOCAL_STT_PRELOAD_ERROR,
            }
        )
        if not model_ready:
            status["detail"] = "Local STT model is not cached; upload transcription may time out until it is downloaded or another STT provider is configured."
        return status

    if provider == "volcengine":
        volc_options = _volcengine_stt_options(config)
        missing = _volcengine_missing_fields(volc_options)
        runtime = "volcengine-v2-ws" if volc_options.get("api_version") == "v2" else "volcengine-sauc-ws"
        status.update(
            {
                "ready": not missing,
                "credential_present": bool(volc_options["app_key"] and volc_options["access_key"]),
                "app_key_present": bool(volc_options["app_key"]),
                "access_key_present": bool(volc_options["access_key"]),
                "secret_key_present": bool(volc_options["secret_key"]),
                "api_version": volc_options["api_version"],
                "cluster_present": bool(volc_options["cluster"]),
                "resource_id": volc_options["resource_id"],
                "runtime": runtime,
                "ws_url": volc_options["v2_ws_url"] if volc_options.get("api_version") == "v2" else volc_options["ws_url"],
            }
        )
        if missing:
            status["detail"] = "Volcengine ASR is missing: " + ", ".join(missing)
        return status

    credential_env = {
        "groq": "GROQ_API_KEY",
        "openai": "VOICE_TOOLS_OPENAI_KEY",
        "mistral": "MISTRAL_API_KEY",
        "xai": "XAI_API_KEY",
    }.get(provider)
    credential_present = bool(credential_env and os.environ.get(credential_env))
    status["credential_present"] = credential_present
    status["ready"] = credential_present
    return status


def _stt_provider_statuses() -> dict[str, Any]:
    volc_options = _volcengine_stt_options()
    missing = _volcengine_missing_fields(volc_options)
    runtime = "volcengine-v2-ws" if volc_options.get("api_version") == "v2" else "volcengine-sauc-ws"
    return {
        "volcengine": {
            "ready": not missing,
            "credential_present": bool(volc_options["app_key"] and volc_options["access_key"]),
            "app_key_present": bool(volc_options["app_key"]),
            "access_key_present": bool(volc_options["access_key"]),
            "secret_key_present": bool(volc_options["secret_key"]),
            "api_version": volc_options["api_version"],
            "cluster_present": bool(volc_options["cluster"]),
            "resource_id": volc_options["resource_id"],
            "runtime": runtime,
            "ws_url": volc_options["v2_ws_url"] if volc_options.get("api_version") == "v2" else volc_options["ws_url"],
            "missing": missing,
        }
    }


def _chat_status() -> dict[str, Any]:
    config = _load_hermes_config()
    model_config = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    provider_name = str(model_config.get("provider") or config.get("provider") or "default")
    providers = config.get("providers", {}) if isinstance(config.get("providers"), dict) else {}
    provider_config = providers.get(provider_name, {}) if isinstance(providers.get(provider_name), dict) else {}

    return {
        "provider": provider_name,
        "model": model_config.get("default") or provider_config.get("default_model") or config.get("model"),
        "base_url": model_config.get("base_url") or provider_config.get("base_url") or config.get("base_url"),
        "context_length": model_config.get("context_length") or config.get("context_length"),
    }


def _tts_status() -> dict[str, Any]:
    config = _load_hermes_config()
    tts_config = config.get("tts", {}) if isinstance(config.get("tts"), dict) else {}
    provider = str(tts_config.get("provider") or "edge")
    provider_config = tts_config.get(provider, {}) if isinstance(tts_config.get(provider), dict) else {}
    return {
        "enabled": _is_enabled(tts_config.get("enabled"), default=True),
        "provider": provider,
        "voice": provider_config.get("voice"),
        "speed": provider_config.get("speed") or tts_config.get("speed"),
        "ready": _agent_tool_status()["tts_tool"],
    }


def _configured_playback_command() -> list[str] | None:
    if not PI_PLAYBACK_COMMAND:
        return None
    command = shlex.split(PI_PLAYBACK_COMMAND)
    if not command:
        return None
    executable = Path(command[0])
    if executable.is_absolute() and executable.exists():
        return command
    resolved = shutil.which(command[0])
    if not resolved:
        return None
    return [resolved, *command[1:]]


def _find_pi_playback_command(audio_path: Path | None = None) -> list[str] | None:
    configured = _configured_playback_command()
    if configured:
        return [*configured, str(audio_path)] if audio_path else configured

    candidates = [
        ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"]),
        ("mpv", ["mpv", "--no-video", "--really-quiet"]),
        ("cvlc", ["cvlc", "--play-and-exit", "--intf", "dummy"]),
        ("play", ["play", "-q"]),
        ("paplay", ["paplay"]),
        ("aplay", ["aplay", "-q"]),
        ("afplay", ["afplay"]),
    ]
    for binary, command in candidates:
        executable = shutil.which(binary)
        if executable:
            resolved = [executable, *command[1:]]
            return [*resolved, str(audio_path)] if audio_path else resolved
    return None


def _alsa_hardware_devices(command: str) -> list[dict[str, Any]]:
    binary = shutil.which(command)
    if not binary:
        return []
    try:
        proc = subprocess.run(
            [binary, "-l"],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    devices: list[dict[str, Any]] = []
    pattern = re.compile(
        r"card\s+(?P<card_index>\d+):\s+(?P<card_name>[^\s]+)\s+\[(?P<card_label>[^\]]+)\],\s+"
        r"device\s+(?P<device_index>\d+):\s+(?P<device_label>[^\[]+)(?:\[(?P<device_detail>[^\]]+)\])?"
    )
    for line in output.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        card_name = match.group("card_name")
        device_index = match.group("device_index")
        device = f"plughw:CARD={card_name},DEV={device_index}"
        devices.append(
            {
                "device": device,
                "card_index": int(match.group("card_index")),
                "card_name": card_name,
                "card_label": match.group("card_label").strip(),
                "device_index": int(device_index),
                "device_label": match.group("device_label").strip(),
                "device_detail": (match.group("device_detail") or "").strip(),
                "raw": line.strip(),
            }
        )
    return devices


def _is_hdmi_alsa_device(device: dict[str, Any]) -> bool:
    text = " ".join(
        str(device.get(key) or "")
        for key in ("card_name", "card_label", "device_label", "device_detail", "raw")
    ).lower()
    return "hdmi" in text or "vc4" in text


def _pi_playback_candidate_devices() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    def add(device: dict[str, Any]) -> None:
        name = str(device.get("device") or "").strip()
        if name and all(item.get("device") != name for item in candidates):
            candidates.append(device)

    if PI_PLAYBACK_DEVICE:
        add({"device": PI_PLAYBACK_DEVICE, "source": "configured"})

    hardware = _alsa_hardware_devices("aplay")
    for device in [item for item in hardware if not _is_hdmi_alsa_device(item)]:
        device["source"] = "aplay -l"
        add(device)
    for device in [item for item in hardware if _is_hdmi_alsa_device(item)]:
        device["source"] = "aplay -l"
        add(device)

    return candidates


def _direct_alsa_playback_device() -> str | None:
    candidates = _pi_playback_candidate_devices()
    return str(candidates[0]["device"]) if candidates else None


def _can_play_direct_alsa() -> bool:
    return bool(_direct_alsa_playback_device() and shutil.which("ffmpeg") and shutil.which("aplay"))


def _pi_playback_status() -> dict[str, Any]:
    candidates = _pi_playback_candidate_devices()
    device = str(candidates[0]["device"]) if candidates else None
    direct = bool(device and shutil.which("ffmpeg") and shutil.which("aplay"))
    command = _find_pi_playback_command()
    return {
        "available": bool(direct or command),
        "ready": bool(direct or command),
        "player": "ffmpeg+aplay" if direct else Path(command[0]).name if command else None,
        "device": device,
        "candidate_devices": candidates[:8],
        "configured": bool(PI_PLAYBACK_COMMAND),
        "configured_device": PI_PLAYBACK_DEVICE or None,
    }


def _audio_cache_path_from_url(audio_url: str) -> Path:
    raw = str(audio_url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="audio_url is required")

    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme or parsed.netloc else raw.split("?", 1)[0]
    if not path.startswith("/audio/"):
        raise HTTPException(status_code=400, detail="audio_url must point to /audio/")

    relative = unquote(path.removeprefix("/audio/"))
    full = (AUDIO_CACHE / relative).resolve()
    try:
        full.relative_to(AUDIO_CACHE.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    if not full.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return full


def _play_audio_on_pi(audio_url: str, *, wait: bool = False) -> dict[str, Any]:
    audio_path = _audio_cache_path_from_url(audio_url)
    device = _direct_alsa_playback_device()
    if device and shutil.which("ffmpeg") and shutil.which("aplay"):
        ffmpeg_cmd = [
            str(shutil.which("ffmpeg")),
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "wav",
            "-",
        ]
        aplay_cmd = [
            str(shutil.which("aplay")),
            "-q",
            "-D",
            device,
            "-",
        ]
        try:
            decoder = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            player = subprocess.Popen(
                aplay_cmd,
                stdin=decoder.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            if decoder.stdout:
                decoder.stdout.close()
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"Could not start local audio playback: {exc}") from exc

        def wait_for_playback() -> None:
            try:
                player.wait(timeout=PI_PLAYBACK_TIMEOUT)
            except subprocess.TimeoutExpired as exc:
                if player.poll() is None:
                    player.terminate()
                if decoder.poll() is None:
                    decoder.terminate()
                raise HTTPException(status_code=504, detail="Raspberry Pi audio playback timed out") from exc
            finally:
                if decoder.poll() is None:
                    decoder.terminate()
                try:
                    decoder.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    decoder.kill()
                    decoder.wait()

        if wait:
            wait_for_playback()
        else:
            def clean_up_playback() -> None:
                try:
                    wait_for_playback()
                except HTTPException:
                    pass

            threading.Thread(target=clean_up_playback, daemon=True).start()
        return {
            "ok": True,
            "audio_url": audio_url,
            "player": "ffmpeg+aplay",
            "device": device,
            "completed": wait,
        }

    command = _find_pi_playback_command(audio_path)
    if not command:
        raise HTTPException(
            status_code=503,
            detail="No local audio player found. Install ffplay/mpv/cvlc or set VOICE_WEB_PI_PLAYBACK_COMMAND.",
        )

    try:
        player = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Could not start local audio playback: {exc}") from exc

    if wait:
        try:
            player.wait(timeout=PI_PLAYBACK_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            if player.poll() is None:
                player.terminate()
            raise HTTPException(status_code=504, detail="Raspberry Pi audio playback timed out") from exc

    return {
        "ok": True,
        "audio_url": audio_url,
        "player": Path(command[0]).name,
        "completed": wait,
    }


def _find_arecord() -> str | None:
    return shutil.which("arecord")


def _pi_record_candidate_devices(recorder: str | None = None) -> list[str]:
    recorder = recorder or _find_arecord()
    configured = PI_RECORD_DEVICE.strip()
    candidates: list[str] = []

    def add(device: str) -> None:
        if device and device not in candidates:
            candidates.append(device)

    if configured:
        add(configured)

    for device in _alsa_hardware_devices("arecord") if recorder else []:
        add(str(device["device"]))

    return candidates


def _pi_record_status() -> dict[str, Any]:
    recorder = _find_arecord()
    candidates = _pi_record_candidate_devices(recorder) if recorder else []
    ready = bool(recorder and candidates)
    detail = None
    if recorder and not candidates:
        detail = "No ALSA capture hardware device was detected. Connect a USB microphone or set VOICE_WEB_PI_RECORD_DEVICE to a valid capture PCM."
    return {
        "available": ready,
        "ready": ready,
        "recorder": recorder,
        "device": PI_RECORD_DEVICE or (candidates[0] if candidates else None),
        "configured_device": PI_RECORD_DEVICE or None,
        "candidate_devices": candidates[:8],
        "rate": PI_RECORD_RATE,
        "channels": PI_RECORD_CHANNELS,
        "detail": detail,
    }


def _load_agent_tool(module_name: str, attr_name: str) -> Any:
    if not HERMES_AGENT.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Hermes agent not found at {HERMES_AGENT}. Set HERMES_AGENT to the hermes-agent directory.",
        )

    agent_path = str(HERMES_AGENT)
    if agent_path not in sys.path:
        sys.path.insert(0, agent_path)

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not load {module_name} from {HERMES_AGENT}: {exc}",
        ) from exc

    try:
        return getattr(module, attr_name)
    except AttributeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{module_name} does not expose {attr_name}",
        ) from exc


def _get_inline_local_stt_model(options: dict[str, Any]) -> Any:
    key = _local_stt_cache_key(options)
    model = LOCAL_STT_MODEL_CACHE.get(key)
    if model is not None:
        return model

    from faster_whisper import WhisperModel

    kwargs: dict[str, Any] = {
        "device": options["device"],
        "compute_type": options["compute_type"],
    }
    if options.get("cpu_threads"):
        kwargs["cpu_threads"] = options["cpu_threads"]

    model_source = str(options.get("model_path") or options["model"])
    model = WhisperModel(model_source, **kwargs)
    LOCAL_STT_MODEL_CACHE[key] = model
    return model


def _transcribe_local_audio_inline(path: str) -> dict[str, Any]:
    options = _local_stt_options()
    language = str(options["language"])
    language_arg = None if language in {"", "auto", "none"} else language

    with LOCAL_STT_LOCK:
        model = _get_inline_local_stt_model(options)
        started = time.monotonic()
        segments, info = model.transcribe(
            path,
            language=language_arg,
            vad_filter=bool(options["vad_filter"]),
        )
        transcript = "".join(str(segment.text or "") for segment in segments).strip()
        elapsed = round(time.monotonic() - started, 3)

    return {
        "success": True,
        "transcript": transcript,
        "language": getattr(info, "language", language_arg),
        "duration": getattr(info, "duration", None),
        "runtime": "inline-cache",
        "elapsed_seconds": elapsed,
    }


def _volcengine_headers(options: dict[str, Any], request_id: str) -> dict[str, str]:
    return {
        "X-Api-App-Key": options["app_key"],
        "X-Api-Access-Key": options["access_key"],
        "X-Api-Resource-Id": options["resource_id"],
        "X-Api-Connect-Id": request_id,
    }


def _volcengine_audio_format(path: Path, configured: str = "") -> str:
    if configured:
        return configured.lstrip(".")
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"wav", "mp3", "ogg", "flac", "m4a", "aac", "webm"}:
        return suffix
    return "wav"


def _volcengine_binary_packet(
    payload: bytes,
    *,
    message_type: int,
    flags: int = 0,
    serialization: int = 0,
    compression: int = 0,
) -> bytes:
    header = bytes(
        [
            0x10 | 0x01,
            ((message_type & 0x0F) << 4) | (flags & 0x0F),
            ((serialization & 0x0F) << 4) | (compression & 0x0F),
            0x00,
        ]
    )
    return header + len(payload).to_bytes(4, "big", signed=False) + payload


def _volcengine_json_packet(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _volcengine_binary_packet(
        gzip.compress(encoded),
        message_type=0x1,
        serialization=0x1,
        compression=0x1,
    )


def _volcengine_audio_packet(payload: bytes, *, final: bool = False) -> bytes:
    return _volcengine_binary_packet(
        gzip.compress(payload),
        message_type=0x2,
        flags=0x2 if final else 0x0,
        compression=0x1,
    )


def _parse_volcengine_binary_response(message: bytes | str) -> dict[str, Any]:
    if isinstance(message, str):
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError:
            return {"message": message}
        return parsed if isinstance(parsed, dict) else {"payload": parsed}
    if len(message) < 4:
        return {}

    header_size = (message[0] & 0x0F) * 4
    message_type = (message[1] >> 4) & 0x0F
    flags = message[1] & 0x0F
    serialization = (message[2] >> 4) & 0x0F
    compression = message[2] & 0x0F
    offset = header_size
    sequence = None
    if flags in {0x1, 0x2, 0x3} and len(message) >= offset + 4 and message_type == 0xB:
        sequence = int.from_bytes(message[offset : offset + 4], "big", signed=True)
        offset += 4
    if message_type == 0xF:
        if len(message) < offset + 8:
            return {"message_type": message_type, "flags": flags, "sequence": sequence}
        error_code = int.from_bytes(message[offset : offset + 4], "big", signed=False)
        offset += 4
        payload_size = int.from_bytes(message[offset : offset + 4], "big", signed=False)
        offset += 4
        payload = message[offset : offset + payload_size]
        if compression == 0x1 and payload:
            try:
                payload = gzip.decompress(payload)
            except OSError:
                pass
        return {
            "message_type": message_type,
            "flags": flags,
            "sequence": sequence,
            "error_code": error_code,
            "payload": payload.decode("utf-8", errors="replace") if payload else "",
        }
    if len(message) < offset + 4:
        return {"message_type": message_type, "flags": flags, "sequence": sequence}

    payload_size = int.from_bytes(message[offset : offset + 4], "big", signed=False)
    offset += 4
    payload = message[offset : offset + payload_size]
    if compression == 0x1 and payload:
        try:
            payload = gzip.decompress(payload)
        except OSError:
            pass

    parsed_payload: Any
    if serialization == 0x1 and payload:
        try:
            parsed_payload = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed_payload = payload.decode("utf-8", errors="replace")
    else:
        parsed_payload = payload.decode("utf-8", errors="replace") if payload else ""

    return {
        "message_type": message_type,
        "flags": flags,
        "sequence": sequence,
        "payload": parsed_payload,
    }


def _extract_volcengine_stream_transcript(payload: dict[str, Any]) -> str:
    nested = payload.get("payload")
    if isinstance(nested, dict):
        transcript = _extract_volcengine_transcript(nested)
        if transcript:
            return transcript
        result = nested.get("result")
        if isinstance(result, dict):
            transcript = _extract_volcengine_transcript(result)
            if transcript:
                return transcript
    return _extract_volcengine_transcript(payload)


def _volcengine_json_request(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Volcengine ASR HTTP {exc.code}: {body[-1000:]}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Volcengine ASR request failed: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Volcengine ASR returned invalid JSON: {body[-1000:]}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Volcengine ASR returned unexpected data")
    return parsed


def _extract_volcengine_transcript(payload: dict[str, Any]) -> str:
    candidates: list[Any] = [
        payload.get("text"),
        payload.get("transcript"),
        payload.get("utterance"),
        payload.get("result") if isinstance(payload.get("result"), list) else None,
        payload.get("result", {}).get("text") if isinstance(payload.get("result"), dict) else None,
    ]
    result = payload.get("result")
    if isinstance(result, dict):
        candidates.extend(
            [
                result.get("utterances"),
                result.get("sentences"),
                result.get("results"),
            ]
        )

    parts: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            parts.append(candidate.strip())
        elif isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
                elif isinstance(item, dict):
                    text = str(item.get("text") or item.get("utterance") or "").strip()
                    if text:
                        parts.append(text)
    return "".join(parts).strip()


def _prepare_volcengine_v2_audio(audio_path: Path) -> tuple[Path, Path | None]:
    if audio_path.suffix.lower() == ".wav":
        return audio_path, None

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="Volcengine ASR v2 requires ffmpeg to convert non-WAV audio")
    tmp = tempfile.NamedTemporaryFile(prefix="volc_asr_", suffix=".wav", dir=UPLOAD_DIR if UPLOAD_DIR.exists() else None, delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(audio_path),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-acodec",
                "pcm_s16le",
                str(tmp_path),
            ],
            text=True,
            capture_output=True,
            timeout=60,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        tmp_path.unlink(missing_ok=True)
        detail = (exc.stderr or exc.stdout or "ffmpeg conversion failed").strip()
        raise HTTPException(status_code=502, detail=detail[-1000:]) from exc
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path, tmp_path


def _volcengine_v2_segment_size(path: Path, seg_duration_ms: int) -> int:
    try:
        with wave.open(str(path), "rb") as wave_file:
            channels, sample_width, frame_rate = wave_file.getparams()[:3]
        return max(1024, int(channels * sample_width * frame_rate * seg_duration_ms / 1000))
    except wave.Error:
        return max(1024, int(32000 * seg_duration_ms / 1000))


def _volcengine_v2_request_payload(options: dict[str, Any], request_id: str) -> dict[str, Any]:
    return {
        "app": {
            "appid": options["app_key"],
            "token": options["access_key"],
            "cluster": options["cluster"],
        },
        "user": {"uid": "voice-web"},
        "audio": {
            "format": "wav",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
            "language": options["language"],
            "codec": "raw",
        },
        "request": {
            "reqid": request_id,
            "nbest": 1,
            "workflow": options["workflow"],
            "show_utterances": True,
            "result_type": options["result_type"],
            "sequence": 1,
        },
    }


def _transcribe_volcengine_v2_audio(path: str) -> dict[str, Any]:
    options = _volcengine_stt_options()
    missing = _volcengine_missing_fields(options)
    if missing:
        raise HTTPException(status_code=503, detail="Volcengine ASR is missing: " + ", ".join(missing))

    audio_path = Path(path)
    if not audio_path.exists():
        raise HTTPException(status_code=400, detail="Audio file does not exist")

    try:
        from websockets.sync.client import connect
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Volcengine ASR requires the websockets package: {exc}") from exc

    prepared_path, temporary_path = _prepare_volcengine_v2_audio(audio_path)
    request_id = str(uuid4())
    started = time.monotonic()
    last_payload: dict[str, Any] | None = None
    transcript = ""
    try:
        headers = {"Authorization": f"Bearer; {options['access_key']}"}
        init_payload = _volcengine_v2_request_payload(options, request_id)
        segment_size = _volcengine_v2_segment_size(prepared_path, int(options["seg_duration_ms"]))
        audio_data = prepared_path.read_bytes()
        chunks = [audio_data[index : index + segment_size] for index in range(0, len(audio_data), segment_size)] or [b""]
        with connect(
            options["v2_ws_url"],
            additional_headers=headers,
            open_timeout=min(options["timeout"], 30),
            close_timeout=2,
            max_size=1000000000,
        ) as websocket:
            websocket.send(_volcengine_json_packet(init_payload))
            first_response = _parse_volcengine_binary_response(websocket.recv(timeout=min(options["timeout"], 30)))
            last_payload = first_response
            payload = first_response.get("payload")
            code = payload.get("code") if isinstance(payload, dict) else None
            if code not in (None, 1000, "1000"):
                raise HTTPException(status_code=502, detail=f"Volcengine ASR failed: {json.dumps(payload, ensure_ascii=False)[-1000:]}")

            for index, chunk in enumerate(chunks):
                websocket.send(_volcengine_audio_packet(chunk, final=index == len(chunks) - 1))
                response = _parse_volcengine_binary_response(websocket.recv(timeout=min(options["timeout"], 30)))
                last_payload = response
                payload = response.get("payload")
                code = payload.get("code") if isinstance(payload, dict) else None
                if code not in (None, 1000, "1000"):
                    raise HTTPException(status_code=502, detail=f"Volcengine ASR failed: {json.dumps(payload, ensure_ascii=False)[-1000:]}")
                next_transcript = _extract_volcengine_stream_transcript(response)
                if next_transcript:
                    transcript = next_transcript
        if not transcript:
            raise HTTPException(status_code=502, detail=f"Volcengine ASR returned no transcript: {json.dumps(last_payload, ensure_ascii=False)[-1000:]}")
        return {
            "success": True,
            "transcript": transcript,
            "provider": "volcengine",
            "runtime": "volcengine-v2-ws",
            "request_id": request_id,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Volcengine ASR websocket failed: {exc}") from exc
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


def _transcribe_volcengine_sauc_audio(path: str) -> dict[str, Any]:
    options = _volcengine_stt_options()
    missing = [
        name
        for name, value in (
            ("app_key", options["app_key"]),
            ("access_key", options["access_key"]),
            ("ws_url", options["ws_url"]),
            ("resource_id", options["resource_id"]),
        )
        if not value
    ]
    if missing:
        raise HTTPException(status_code=503, detail="Volcengine ASR is missing: " + ", ".join(missing))

    audio_path = Path(path)
    if not audio_path.exists():
        raise HTTPException(status_code=400, detail="Audio file does not exist")

    request_id = uuid4().hex
    headers = _volcengine_headers(options, request_id)
    audio_format = _volcengine_audio_format(audio_path, options.get("audio_format", ""))
    init_payload = {
        "user": {"uid": "voice-web"},
        "audio": {
            "format": audio_format,
            "rate": PI_RECORD_RATE,
            "bits": 16,
            "channel": PI_RECORD_CHANNELS,
            "language": options["language"],
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
        },
    }

    started = time.monotonic()
    try:
        from websockets.sync.client import connect
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Volcengine ASR requires the websockets package: {exc}") from exc

    try:
        with connect(options["ws_url"], additional_headers=headers, open_timeout=min(options["timeout"], 30)) as websocket:
            websocket.send(_volcengine_json_packet(init_payload))
            first_response = _parse_volcengine_binary_response(websocket.recv(timeout=min(options["timeout"], 30)))
            first_text = _extract_volcengine_stream_transcript(first_response)
            if first_text:
                return {
                    "success": True,
                    "transcript": first_text,
                    "provider": "volcengine",
                    "runtime": "volcengine-sauc-ws",
                    "request_id": request_id,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }

            chunk_size = int(options["chunk_size"])
            with audio_path.open("rb") as audio_file:
                while True:
                    chunk = audio_file.read(chunk_size)
                    if not chunk:
                        break
                    websocket.send(_volcengine_audio_packet(chunk))
            websocket.send(_volcengine_audio_packet(b"", final=True))

            deadline = started + options["timeout"]
            last_payload: dict[str, Any] = first_response
            while time.monotonic() < deadline:
                response = _parse_volcengine_binary_response(websocket.recv(timeout=min(max(deadline - time.monotonic(), 1.0), 30)))
                last_payload = response
                transcript = _extract_volcengine_stream_transcript(response)
                if transcript:
                    return {
                        "success": True,
                        "transcript": transcript,
                        "provider": "volcengine",
                        "runtime": "volcengine-sauc-ws",
                        "request_id": request_id,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                    }
                payload = response.get("payload")
                code = payload.get("code") if isinstance(payload, dict) else None
                if code not in (None, 0, "0"):
                    raise HTTPException(status_code=502, detail=f"Volcengine ASR failed: {json.dumps(payload, ensure_ascii=False)[-1000:]}")
            raise HTTPException(status_code=504, detail=f"Volcengine ASR timed out: {json.dumps(last_payload, ensure_ascii=False)[-1000:]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Volcengine ASR websocket failed: {exc}") from exc


def _transcribe_volcengine_audio(path: str) -> dict[str, Any]:
    options = _volcengine_stt_options()
    if options.get("api_version") == "v2":
        return _transcribe_volcengine_v2_audio(path)
    return _transcribe_volcengine_sauc_audio(path)


def _transcribe_audio_subprocess(path: str) -> dict[str, Any]:
    python = HERMES_AGENT / "venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)

    script = """
import json
import os
import sys

agent = os.environ["HERMES_AGENT"]
if agent not in sys.path:
    sys.path.insert(0, agent)

from tools.transcription_tools import transcribe_audio

print(json.dumps(transcribe_audio(sys.argv[1]), ensure_ascii=False))
"""
    env = os.environ.copy()
    env["HERMES_HOME"] = str(HERMES_HOME)
    env["HERMES_AGENT"] = str(HERMES_AGENT)
    env["PATH"] = f"{HERMES_AGENT / 'venv' / 'bin'}{os.pathsep}{env.get('PATH', '')}"

    try:
        proc = subprocess.run(
            [str(python), "-c", script, path],
            text=True,
            capture_output=True,
            timeout=STT_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Speech transcription timed out after {STT_TIMEOUT} seconds",
        ) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Could not run speech transcription: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Transcription command failed").strip()
        raise HTTPException(status_code=500, detail=detail[-2000:])

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        detail = (proc.stderr or proc.stdout or "Transcription returned invalid JSON").strip()
        raise HTTPException(status_code=500, detail=detail[-2000:]) from exc


def _transcribe_audio(path: str) -> dict[str, Any]:
    config = _load_hermes_config()
    stt_config = config.get("stt", {}) if isinstance(config, dict) else {}
    provider = str(stt_config.get("provider") or "local")
    if provider == "volcengine":
        return _transcribe_volcengine_audio(path)

    if _should_use_inline_local_stt():
        try:
            return _transcribe_local_audio_inline(path)
        except Exception:
            if not _is_enabled(os.environ.get("VOICE_WEB_STT_SUBPROCESS_FALLBACK"), default=True):
                raise

    return _transcribe_audio_subprocess(path)


def _preload_local_stt_model() -> None:
    global LOCAL_STT_PRELOAD_ERROR
    if not _should_use_inline_local_stt():
        return
    try:
        with LOCAL_STT_LOCK:
            _get_inline_local_stt_model(_local_stt_options())
        LOCAL_STT_PRELOAD_ERROR = None
    except Exception as exc:
        LOCAL_STT_PRELOAD_ERROR = str(exc) or exc.__class__.__name__


@app.on_event("startup")
async def _startup_preload_local_stt() -> None:
    if _preload_local_stt_enabled():
        threading.Thread(target=_preload_local_stt_model, daemon=True).start()


def _text_to_speech(text: str) -> str:
    return _load_agent_tool("tools.tts_tool", "text_to_speech_tool")(text)


def _find_hermes_cli() -> str | None:
    candidates = [
        shutil.which("hermes"),
        HERMES_AGENT / "venv" / "bin" / "hermes",
        HERMES_AGENT / "hermes",
        Path.home() / ".local/bin/hermes",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def _clean_reply(output: str) -> str:
    if _looks_like_denied_command_output(output):
        return COMMAND_DENIED_REPLY

    lines = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _is_hermes_runtime_notice(stripped):
            continue
        if stripped.startswith("session_id:"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _plain_speech_reply(output: str) -> str:
    text = _clean_reply(output)
    if not text:
        return ""

    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    cleaned_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?", line):
            continue
        line = line.strip("|")
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^(?:[-*+]|[0-9]+[.)、]|[一二三四五六七八九十]+[.)、])\s+", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"__(.*?)__", r"\1", line)
        line = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", line)
        line = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = line.replace("**", "").replace("__", "")
        line = line.replace("|", "，")
        line = re.sub(r"([：:])\s+", r"\1", line)
        line = line.strip()
        if line:
            cleaned_lines.append(line)

    text = " ".join(cleaned_lines)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([，。！？；：、])", r"\1", text)
    text = re.sub(r"([（《])\s+", r"\1", text)
    text = re.sub(r"\s+([））》])", r"\1", text)
    return text.strip()


def _looks_like_denied_command_output(output: str) -> bool:
    return any(marker in output for marker in COMMAND_DENIED_MARKERS)


def _is_hermes_runtime_notice(line: str) -> bool:
    return line.startswith("⚠") and any(marker in line for marker in HERMES_RUNTIME_NOTICE_MARKERS)


class WeatherLocationRequired(Exception):
    pass


class WeatherLookupError(Exception):
    def __init__(self, detail: str, status_code: int = 503) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _weather_status() -> dict[str, Any]:
    return {
        "enabled": True,
        "provider": "Open-Meteo",
        "ready": True,
        "default_location": WEATHER_DEFAULT_LOCATION or None,
    }


def _briefing_status() -> dict[str, Any]:
    reminder_count = len(_list_reminders(include_done=False))
    return {
        "enabled": True,
        "ready": True,
        "weather_provider": "Open-Meteo",
        "default_weather_location": WEATHER_DEFAULT_LOCATION or None,
        "reminder_count": reminder_count,
    }


def _reminders_status() -> dict[str, Any]:
    reminders = _list_reminders(include_done=False)
    return {
        "enabled": True,
        "ready": True,
        "file": str(REMINDERS_FILE),
        "open_count": len(reminders),
    }


def _is_weather_query(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return any(marker in compact for marker in WEATHER_QUERY_MARKERS)


def _is_briefing_query(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return any(marker in compact for marker in BRIEFING_QUERY_MARKERS)


def _clean_weather_location_candidate(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"[，。！？；：,.!?;:\(\)（）【】\[\]\"'“”‘’]", " ", text)
    replacements = [
        ASSISTANT_NAME,
        "生活助手小七",
        "小七",
        USER_NAME,
        "请帮我",
        "能不能",
        "可以",
        "帮我",
        "给我",
        "麻烦你",
        "麻烦",
        "请问",
        "请",
        "告诉我",
        "查询",
        "查一下",
        "查查",
        "查",
        "问一下",
        "问问",
        "看一下",
        "看看",
        "一下",
        "实时",
        "现在",
        "当前",
        "今日",
        "每日",
        "今天",
        "明天",
        "后天",
        "今晚",
        "早上",
        "上午",
        "中午",
        "下午",
        "晚上",
        "最近",
        "这周",
        "本周",
        "周末",
        "天气",
        "气温",
        "温度",
        "降雨",
        "降水",
        "下雨",
        "下雪",
        "雨伞",
        "带伞",
        "要不要",
        "需不需要",
        "会不会",
        "是不是",
        "怎么样",
        "如何",
        "多少",
        "适合",
        "穿什么",
        "出门",
        "冷不冷",
        "热不热",
        "风大不大",
        "风大",
        "我这边",
        "本地",
        "这里",
        "这儿",
        "附近",
        "当地",
        "简报",
        "早安",
        "早上好",
        "播报一下",
    ]
    for word in replacements:
        text = text.replace(word, " ")
    text = re.sub(r"\b(today|tomorrow|weather|forecast|temperature|rain|snow|umbrella|local|nearby)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" 的在到去给帮我查问看")
    return text.strip()


def _extract_weather_location(text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    patterns = [
        r"(?:查(?:一下)?|查询|看看|看一下|告诉我)?\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z\s·.-]{0,32}?)(?:的)?(?:实时)?(?:天气|气温|温度|降雨|降水|下雨|下雪|雨伞|带伞|冷不冷|热不热|风大|穿什么)",
        r"(?:天气|气温|温度|降雨|降水|下雨|下雪|雨伞|带伞|冷不冷|热不热|风大|穿什么).{0,12}?(?:在|到|去|查)\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z\s·.-]{0,32})",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.I)
        if match:
            candidate = _clean_weather_location_candidate(match.group(1))
            if len(candidate) >= 2:
                return candidate

    candidate = _clean_weather_location_candidate(raw)
    return candidate if len(candidate) >= 2 else None


def _weather_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Hermes Voice Web/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=WEATHER_TIMEOUT) as response:
            payload = response.read().decode("utf-8")
    except Exception as exc:
        raise WeatherLookupError(f"天气服务暂时不可用：{exc}") from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise WeatherLookupError("天气服务返回了无法解析的数据") from exc
    if not isinstance(data, dict):
        raise WeatherLookupError("天气服务返回的数据格式不正确")
    return data


def _geocode_weather_location(location: str) -> dict[str, Any]:
    query = urlencode(
        {
            "name": location,
            "count": 1,
            "language": "zh",
            "format": "json",
        }
    )
    data = _weather_json(f"https://geocoding-api.open-meteo.com/v1/search?{query}")
    results = data.get("results") if isinstance(data.get("results"), list) else []
    if not results:
        raise WeatherLookupError(f"没有找到“{location}”的天气地点，请换一个城市名。", status_code=404)
    result = results[0]
    if not isinstance(result, dict) or result.get("latitude") is None or result.get("longitude") is None:
        raise WeatherLookupError(f"天气地点“{location}”缺少坐标信息。", status_code=502)
    return result


def _weather_code_label(value: Any) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return "未知"
    return WEATHER_CODE_DESCRIPTIONS.get(code, f"天气代码 {code}")


def _format_number(value: Any, unit: str = "", digits: int = 0) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{value}{unit}"
    formatted = f"{number:.{digits}f}" if digits else f"{round(number):.0f}"
    return f"{formatted}{unit}"


def _format_wind_direction(value: Any) -> str:
    try:
        degrees = float(value)
    except (TypeError, ValueError):
        return "-"
    directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    return directions[int((degrees + 22.5) // 45) % 8]


def _daily_row(daily: dict[str, Any], index: int) -> str | None:
    dates = daily.get("time") if isinstance(daily.get("time"), list) else []
    if index >= len(dates):
        return None

    def item(key: str) -> Any:
        values = daily.get(key)
        return values[index] if isinstance(values, list) and index < len(values) else None

    label = ("今天", "明天", "后天")[index] if index < 3 else f"第{index + 1}天"
    return (
        f"{label} {dates[index]}：{_weather_code_label(item('weather_code'))}，"
        f"{_format_number(item('temperature_2m_min'), '°C')}~{_format_number(item('temperature_2m_max'), '°C')}，"
        f"最高降水概率 {_format_number(item('precipitation_probability_max'), '%')}，"
        f"降水量 {_format_number(item('precipitation_sum'), 'mm', 1)}，"
        f"最大风速 {_format_number(item('wind_speed_10m_max'), 'km/h')}，"
        f"UV {_format_number(item('uv_index_max'), '', 1)}"
    )


def _fetch_weather(location: str) -> dict[str, Any]:
    place = _geocode_weather_location(location)
    params = urlencode(
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "precipitation",
                    "rain",
                    "showers",
                    "snowfall",
                    "weather_code",
                    "cloud_cover",
                    "wind_speed_10m",
                    "wind_direction_10m",
                ]
            ),
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_sum",
                    "precipitation_probability_max",
                    "wind_speed_10m_max",
                    "uv_index_max",
                ]
            ),
            "forecast_days": 3,
            "timezone": "auto",
        }
    )
    forecast = _weather_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    forecast["resolved_location"] = place
    forecast["requested_location"] = location
    forecast["source"] = "Open-Meteo"
    return forecast


def _format_weather_context(weather: dict[str, Any]) -> str:
    place = weather.get("resolved_location") if isinstance(weather.get("resolved_location"), dict) else {}
    current = weather.get("current") if isinstance(weather.get("current"), dict) else {}
    daily = weather.get("daily") if isinstance(weather.get("daily"), dict) else {}
    name_parts = [
        str(place.get("name") or weather.get("requested_location") or "").strip(),
        str(place.get("admin1") or "").strip(),
        str(place.get("country") or "").strip(),
    ]
    location_name = " / ".join(part for part in name_parts if part)
    wind_speed = _format_number(current.get("wind_speed_10m"), "km/h")
    wind_direction = _format_wind_direction(current.get("wind_direction_10m"))
    lines = [
        "WEATHER_CONTEXT:",
        "来源：Open-Meteo 实时天气与未来三天预报。",
        f"查询生成时间：{_now()}。",
        f"地点：{location_name or '-'}；时区：{weather.get('timezone') or '-'}；坐标：{place.get('latitude')}, {place.get('longitude')}。",
        (
            f"当前（{current.get('time') or '-'}）：{_weather_code_label(current.get('weather_code'))}，"
            f"温度 {_format_number(current.get('temperature_2m'), '°C')}，"
            f"体感 {_format_number(current.get('apparent_temperature'), '°C')}，"
            f"湿度 {_format_number(current.get('relative_humidity_2m'), '%')}，"
            f"云量 {_format_number(current.get('cloud_cover'), '%')}，"
            f"降水 {_format_number(current.get('precipitation'), 'mm', 1)}，"
            f"风 {wind_direction} {wind_speed}。"
        ),
        "预报：",
    ]
    for index in range(3):
        row = _daily_row(daily, index)
        if row:
            lines.append(f"- {row}")
    return "\n".join(lines)


def _weather_location_required_reply() -> str:
    return "我可以查实时天气，不过需要先知道城市。你可以说“查上海天气”或“明天北京会不会下雨”。"


def _weather_lookup_failed_reply(error: WeatherLookupError) -> str:
    return f"天气查询暂时失败：{error.detail}"


def _build_weather_context_for_text(user_text: str) -> str | None:
    if not _is_weather_query(user_text):
        return None
    location = _extract_weather_location(user_text) or WEATHER_DEFAULT_LOCATION
    if not location:
        raise WeatherLocationRequired()
    return _format_weather_context(_fetch_weather(location))


def _weather_payload(location: str) -> dict[str, Any]:
    location = str(location or "").strip()
    if not location:
        raise WeatherLocationRequired()
    weather = _fetch_weather(location)
    return {
        "ok": True,
        "source": "Open-Meteo",
        "location": weather.get("resolved_location"),
        "requested_location": location,
        "context": _format_weather_context(weather),
        "weather": weather,
    }


def _extract_briefing_location(text: str) -> str | None:
    if not str(text or "").strip():
        return None
    weather_like = str(text).replace("简报", "天气").replace("早安", "天气").replace("早上好", "天气")
    return _extract_weather_location(weather_like)


def _read_meminfo() -> dict[str, int]:
    data: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            value = rest.strip().split()[0]
            data[key] = int(value) * 1024
    except (OSError, ValueError):
        return {}
    return data


def _system_temperature_c() -> float | None:
    for path in (
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/devices/virtual/thermal/thermal_zone0/temp"),
    ):
        try:
            raw = path.read_text(encoding="utf-8").strip()
            return round(float(raw) / 1000, 1)
        except (OSError, ValueError):
            continue
    return None


def _service_state(name: str) -> str:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", name],
            text=True,
            capture_output=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    state = (proc.stdout or proc.stderr or "").strip()
    return state or "unknown"


def _system_snapshot() -> dict[str, Any]:
    meminfo = _read_meminfo()
    mem_total = meminfo.get("MemTotal")
    mem_available = meminfo.get("MemAvailable")
    memory_used_percent = None
    if mem_total and mem_available is not None:
        memory_used_percent = round((1 - mem_available / mem_total) * 100, 1)

    disk = shutil.disk_usage(str(HERMES_HOME))
    uptime_seconds = None
    try:
        uptime_seconds = int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        pass

    return {
        "time_local": datetime.now().astimezone().isoformat(timespec="minutes"),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "",
        "cpu_count": os.cpu_count(),
        "load_average": tuple(round(value, 2) for value in os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "memory_used_percent": memory_used_percent,
        "memory_total_mb": round(mem_total / (1024 * 1024)) if mem_total else None,
        "disk_used_percent": round((disk.used / disk.total) * 100, 1) if disk.total else None,
        "disk_free_gb": round(disk.free / (1024**3), 1),
        "temperature_c": _system_temperature_c(),
        "uptime_seconds": uptime_seconds,
        "services": {
            "hermes-voice-web": _service_state("hermes-voice-web.service"),
            "resp-lanu": _service_state("resp-lanu.service"),
        },
    }


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    days, remainder = divmod(max(0, int(seconds)), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{minutes}分钟"
    return f"{minutes}分钟"


def _format_system_context(snapshot: dict[str, Any]) -> str:
    load = snapshot.get("load_average")
    load_text = "/".join(str(value) for value in load) if load else "-"
    services = snapshot.get("services") if isinstance(snapshot.get("services"), dict) else {}
    return "\n".join(
        [
            "SYSTEM_CONTEXT:",
            f"本地时间：{snapshot.get('time_local') or '-'}。",
            f"主机：{snapshot.get('hostname') or '-'}；CPU 核心：{snapshot.get('cpu_count') or '-'}；负载：{load_text}。",
            (
                f"内存使用：{_format_number(snapshot.get('memory_used_percent'), '%', 1)}"
                f" / 总内存 {_format_number(snapshot.get('memory_total_mb'), 'MB')}；"
                f"磁盘使用：{_format_number(snapshot.get('disk_used_percent'), '%', 1)}"
                f" / 剩余 {_format_number(snapshot.get('disk_free_gb'), 'GB', 1)}。"
            ),
            f"CPU 温度：{_format_number(snapshot.get('temperature_c'), '°C', 1)}；运行时长：{_format_duration(snapshot.get('uptime_seconds'))}。",
            (
                "服务状态："
                f"hermes-voice-web={services.get('hermes-voice-web') or '-'}，"
                f"resp-lanu={services.get('resp-lanu') or '-'}。"
            ),
        ]
    )


def _briefing_payload(location: str | None = None) -> dict[str, Any]:
    location = str(location or "").strip()
    weather_context = None
    weather_error = None
    if location:
        try:
            weather_context = _format_weather_context(_fetch_weather(location))
        except WeatherLookupError as exc:
            weather_error = exc.detail

    system = _system_snapshot()
    reminders = _list_reminders(include_done=False)
    lines = [
        "BRIEFING_CONTEXT:",
        "这是给生活助手生成今日简报的服务端上下文。请用自然中文总结，不要逐项机械照抄。",
        "建议结构：一句总体判断、天气与出门建议、未完成提醒、树莓派/服务状态、今天下一步建议。",
        "涉及日期时必须按上下文里的“今天/明天/后天 + 日期”称呼，不要把后天说成明天。",
        "如果 WEATHER_CONTEXT 包含当前天气或预报，必须把天气视为已查到，禁止说天气查不到、维护中或让用户改查手机天气。",
    ]
    if weather_context:
        lines.append(weather_context)
    elif weather_error:
        lines.append(f"WEATHER_CONTEXT: 天气查询失败：{weather_error}")
    else:
        lines.append("WEATHER_CONTEXT: 未指定天气城市；可以提醒用户说“天津今日简报”或配置默认城市。")
    lines.append(_format_reminders_context(reminders))
    lines.append(_format_system_context(system))
    context = "\n".join(lines)
    return {
        "ok": True,
        "context": context,
        "location": location or None,
        "weather_available": bool(weather_context),
        "weather_error": weather_error,
        "reminder_count": len(reminders),
        "reminders": reminders,
        "system": system,
    }


def _build_briefing_context_for_text(user_text: str) -> str | None:
    if not _is_briefing_query(user_text):
        return None
    location = _extract_briefing_location(user_text) or WEATHER_DEFAULT_LOCATION
    return _briefing_payload(location).get("context")


def _run_hermes(prompt: str) -> str:
    hermes = _find_hermes_cli()
    if not hermes:
        raise HTTPException(
            status_code=503,
            detail="Hermes CLI not found. Install hermes or add it to PATH.",
        )
    env = os.environ.copy()
    env["HERMES_HOME"] = str(HERMES_HOME)
    try:
        proc = subprocess.run(
            [
                hermes,
                "chat",
                "-q",
                prompt,
                "--ignore-rules",
                "--quiet",
                "--source",
                "voice-web",
                "--max-turns",
                str(HERMES_MAX_TURNS),
            ],
            text=True,
            capture_output=True,
            timeout=HERMES_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Hermes timed out after {HERMES_TIMEOUT} seconds while generating a reply",
        ) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Could not run Hermes CLI: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Hermes command failed").strip()
        raise HTTPException(status_code=500, detail=detail[-2000:])
    reply = _clean_reply(proc.stdout)
    if not reply:
        raise HTTPException(status_code=500, detail="Hermes returned an empty reply")
    return reply


def _build_chat_prompt(
    history: list[dict[str, Any]],
    user_text: str,
    *,
    voice: bool = False,
    external_context: str | None = None,
) -> str:
    style = (
        "这次回复会被直接朗读。必须输出纯文本中文口语，不要使用 Markdown，"
        "不要使用星号、井号、项目符号、编号列表、表格或代码块。"
        "天气、提醒和建议请写成几句短句，用逗号和句号自然连接。"
        if voice
        else "请默认使用中文，回答清楚、具体。必要时可以用简洁列表，但不要输出冗余说明。"
    )
    recent = []
    for message in history[-MAX_HISTORY_MESSAGES:]:
        role = USER_NAME if message.get("role") == "user" else ASSISTANT_NAME
        content = str(message.get("content") or "").strip()
        if content:
            recent.append(f"{role}: {content}")

    history_text = "\n".join(recent) if recent else "（暂无历史会话）"
    context_text = (
        "以下是服务端已经查询到的外部实时数据。你必须只基于这些数据回答相关实时问题，"
        "并说明地点和数据时间；如果没有相关数据，不要编造：\n"
        f"{external_context}\n\n"
        if external_context
        else ""
    )
    return (
        f"你是{ASSISTANT_NAME}，是{USER_NAME}的生活助手。"
        f"{USER_NAME}的身份画像：{USER_PROFILE}\n"
        "优先帮助用户完成学习上的事情，包括理解知识点、拆解作业、制定复习计划、安排时间、检查思路和督促执行。"
        "保持亲切、清楚、可靠，必要时主动把复杂任务拆成可执行步骤。"
        "当前网页语音助手不能执行 shell 命令、任意 Python/Node 代码或工具调用。"
        "遇到实时天气请求时，如果服务端提供了 WEATHER_CONTEXT，就基于它回答；如果没有，就询问城市或说明暂时无法查询。"
        "只要 WEATHER_CONTEXT 里包含当前天气或预报，就禁止说天气查不到、天气服务维护、或让用户改查手机天气。"
        "遇到今日简报、早安、今天怎么样等请求时，如果服务端提供了 BRIEFING_CONTEXT，就基于它生成简短实用的当天简报。"
        "如果服务端提供了 REMINDER_CONTEXT，就把未完成提醒当作已经记录在本地的事项，不要编造不存在的提醒。"
        "遇到实时价格、联网检索等其他请求时，请直接说明不能实时查询，不要编造结果，"
        "不要输出工具调用、终端日志、命令审批提示或代码块。"
        f"{style}\n\n"
        f"{context_text}"
        "以下是当前网页会话历史，可用于保持上下文：\n"
        f"{history_text}\n\n"
        f"{USER_NAME}: {user_text}\n"
        f"{ASSISTANT_NAME}:"
    )


def _build_direct_voice_prompt(history: list[dict[str, Any]], user_text: str) -> str:
    recent = []
    for message in history[-MAX_HISTORY_MESSAGES:]:
        role = USER_NAME if message.get("role") == "user" else ASSISTANT_NAME
        content = str(message.get("content") or "").strip()
        if content:
            recent.append(f"{role}: {content}")

    history_text = "\n".join(recent) if recent else "（暂无历史会话）"
    return (
        f"你是{ASSISTANT_NAME}，是{USER_NAME}的生活助手。"
        f"{USER_NAME}的身份画像：{USER_PROFILE}\n"
        "下面是网页语音助手识别到的用户语音转写。请把它当作用户直接对 Hermes 提出的请求来完成；"
        "需要实时信息或工具能力时，使用 Hermes 当前可用的原生能力。"
        "回复要自然、简洁，适合直接朗读；必须输出纯文本中文口语。"
        "不要使用 Markdown，不要使用星号、井号、项目符号、编号列表、表格或代码块。"
        "天气、提醒和建议请写成几句短句，用逗号和句号自然连接。"
        "不要解释转写流程，不要输出工具日志。\n\n"
        "当前网页会话历史：\n"
        f"{history_text}\n\n"
        f"{USER_NAME}: {user_text}\n"
        f"{ASSISTANT_NAME}:"
    )


def _speak_reply(reply: str) -> dict[str, Any]:
    tts = _parse_tts_result(_text_to_speech(reply))
    return {
        "audio_url": tts["audio_url"],
        "tts": {
            "provider": tts.get("provider"),
            "voice_compatible": tts.get("voice_compatible"),
        },
    }


def _answer_message(
    session_id: str | None,
    user_text: str,
    *,
    speak: bool = False,
    kind: str = "text",
    duration: int = 0,
) -> dict[str, Any]:
    user_text = str(user_text or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Message is empty")
    if len(user_text) > MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=413, detail=f"Message is longer than {MAX_MESSAGE_CHARS} characters")

    session = _prepare_session(session_id)
    direct_voice = kind == "voice" and DIRECT_HERMES_VOICE
    reply: str | None = None if direct_voice else _handle_reminder_intent(user_text)
    external_context: str | None = None
    if reply is None and not direct_voice:
        external_context = _build_briefing_context_for_text(user_text)
        try:
            if external_context is None:
                external_context = _build_weather_context_for_text(user_text)
        except WeatherLocationRequired:
            reply = _weather_location_required_reply()
        except WeatherLookupError as exc:
            reply = _weather_lookup_failed_reply(exc)

    if reply is None:
        prompt = (
            _build_direct_voice_prompt(session.get("messages") or [], user_text)
            if direct_voice
            else _build_chat_prompt(
                session.get("messages") or [],
                user_text,
                voice=speak or kind == "voice",
                external_context=external_context,
            )
        )
        reply = _run_hermes(
            prompt
        )

    speech: dict[str, Any] = {"audio_url": None, "tts": None}
    if speak:
        reply = _plain_speech_reply(reply)
        speech = _speak_reply(reply)

    now = _now()
    user_message = {
        "id": uuid4().hex[:12],
        "role": "user",
        "content": user_text,
        "kind": kind,
        "created_at": now,
    }
    if duration:
        user_message["duration"] = duration

    assistant_message = {
        "id": uuid4().hex[:12],
        "role": "assistant",
        "content": reply,
        "kind": "voice" if speak else "text",
        "created_at": _now(),
    }
    if speech.get("audio_url"):
        assistant_message["audio_url"] = speech["audio_url"]
    if speech.get("tts"):
        assistant_message["tts"] = speech["tts"]

    saved_session = _append_exchange(session["id"], user_message, assistant_message, user_text)
    return {
        "session_id": saved_session["id"],
        "session": saved_session,
        "sessions": _list_sessions(),
        "user_message": user_message,
        "message": assistant_message,
        "reply": reply,
        "audio_url": speech.get("audio_url"),
        "tts": speech.get("tts"),
    }


def _parse_tts_result(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"raw": raw}

    media = data.get("media_tag") or data.get("file_path") or data.get("path") or data.get("raw") or ""
    match = re.search(r"MEDIA:(\S+)", str(media))
    path = Path(match.group(1) if match else str(data.get("file_path") or ""))
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"TTS audio file not found: {path}")
    try:
        rel = path.resolve().relative_to(AUDIO_CACHE.resolve())
    except ValueError:
        raise HTTPException(status_code=500, detail="TTS audio path is outside the audio cache")
    data["audio_url"] = f"/audio/{rel.as_posix()}"
    return data


def _answer_transcript(transcript: str, duration: int, session_id: str | None = None) -> dict[str, Any]:
    transcript = transcript.strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="No speech was transcribed")

    result = _answer_message(session_id, transcript, speak=True, kind="voice", duration=duration)
    result["duration"] = duration
    result["transcript"] = transcript
    return result


def _answer_audio_path(audio_path: Path, duration: int, session_id: str | None = None) -> dict[str, Any]:
    transcription = _transcribe_audio(str(audio_path))
    if not transcription.get("success"):
        raise HTTPException(status_code=500, detail=transcription.get("error") or "Transcription failed")
    transcript = str(transcription.get("transcript") or "").strip()
    return _answer_transcript(transcript, duration, session_id)


def _create_pi_record_tempfile() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="pi_record_", suffix=".wav", dir=UPLOAD_DIR, delete=False) as tmp:
        return Path(tmp.name)


def _pi_record_command(recorder: str, device: str, duration: int, audio_path: Path) -> list[str]:
    return [
        recorder,
        "-q",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-r",
        str(PI_RECORD_RATE),
        "-c",
        str(PI_RECORD_CHANNELS),
        "-d",
        str(duration),
        str(audio_path),
    ]


def _wav_has_audio(audio_path: Path) -> bool:
    return audio_path.exists() and audio_path.stat().st_size > 44


def _record_pi_audio(duration: int, job_id: str | None = None) -> Path:
    recorder = _find_arecord()
    if not recorder:
        raise HTTPException(status_code=503, detail="arecord not found on this host; Raspberry Pi recording is unavailable")

    candidates = _pi_record_candidate_devices(recorder)
    if not candidates:
        raise HTTPException(
            status_code=503,
            detail="No ALSA capture hardware device was detected. Connect a USB microphone or set VOICE_WEB_PI_RECORD_DEVICE to a valid capture PCM.",
        )

    errors: list[str] = []
    for device in candidates:
        tmp_path = _create_pi_record_tempfile()
        command = _pi_record_command(recorder, device, duration, tmp_path)
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if job_id:
                stop_requested = False
                with PI_RECORD_LOCK:
                    job = PI_RECORD_JOBS.get(job_id)
                    if job:
                        job["device"] = device
                        job["audio_path"] = str(tmp_path)
                        job["proc"] = proc
                        stop_requested = bool(job.get("stop_requested"))
                if stop_requested and proc.poll() is None:
                    try:
                        proc.send_signal(signal.SIGINT)
                    except OSError:
                        try:
                            proc.terminate()
                        except OSError:
                            pass
            stdout, stderr = proc.communicate(timeout=duration + 15)
        except subprocess.TimeoutExpired as exc:
            if proc and proc.poll() is None:
                proc.kill()
                proc.communicate()
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=504, detail=f"Pi recording timed out after {duration} seconds") from exc
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            errors.append(f"{device}: {exc}")
            continue
        finally:
            if job_id:
                with PI_RECORD_LOCK:
                    job = PI_RECORD_JOBS.get(job_id)
                    if job and job.get("proc") is proc:
                        job["proc"] = None

        stopped = False
        if job_id:
            with PI_RECORD_LOCK:
                job = PI_RECORD_JOBS.get(job_id)
                stopped = bool(job and job.get("stop_requested"))

        if stopped and _wav_has_audio(tmp_path):
            return tmp_path

        if proc.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            detail = (stderr or stdout or "Pi recording command failed").strip()
            if stopped:
                raise HTTPException(status_code=400, detail="Pi recording was stopped before usable audio was captured")
            errors.append(f"{device}: {detail[-500:]}")
            continue

        if not _wav_has_audio(tmp_path):
            tmp_path.unlink(missing_ok=True)
            if stopped:
                raise HTTPException(status_code=400, detail="Pi recording was stopped before usable audio was captured")
            errors.append(f"{device}: empty WAV file")
            continue

        return tmp_path

    detail = "; ".join(errors) or "No Raspberry Pi recording devices were found"
    raise HTTPException(status_code=500, detail=detail[-2000:])


def _record_and_answer_on_pi(duration: int, session_id: str | None = None) -> dict[str, Any]:
    audio_path = _record_pi_audio(duration)
    try:
        return _answer_audio_path(audio_path, duration, session_id)
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass


def _prune_pi_record_jobs_unlocked() -> None:
    if len(PI_RECORD_JOBS) <= MAX_PI_RECORD_JOBS:
        return
    finished = [
        job
        for job in PI_RECORD_JOBS.values()
        if job.get("status") in {"complete", "error"}
    ]
    finished.sort(key=lambda item: str(item.get("completed_at") or item.get("started_at") or ""))
    for job in finished[: max(0, len(PI_RECORD_JOBS) - MAX_PI_RECORD_JOBS)]:
        PI_RECORD_JOBS.pop(str(job["id"]), None)


def _serialise_pi_record_job(job: dict[str, Any]) -> dict[str, Any]:
    elapsed = 0
    if job.get("started_monotonic"):
        elapsed = int(max(0, time.monotonic() - float(job["started_monotonic"])))
    payload = {
        "job_id": job["id"],
        "status": job.get("status"),
        "duration": job.get("duration"),
        "elapsed": job.get("elapsed") or elapsed,
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "device": job.get("device"),
        "stop_requested": bool(job.get("stop_requested")),
    }
    if job.get("result") is not None:
        payload["result"] = job["result"]
    if job.get("error") is not None:
        payload["error"] = job["error"]
    if job.get("status_code") is not None:
        payload["status_code"] = job["status_code"]
    return payload


def _get_pi_record_job(job_id: str) -> dict[str, Any]:
    with PI_RECORD_LOCK:
        job = PI_RECORD_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Pi recording job not found")
        return _serialise_pi_record_job(job)


def _run_pi_record_job(job_id: str) -> None:
    with PI_RECORD_LOCK:
        job = PI_RECORD_JOBS.get(job_id)
        if not job:
            return
        duration = int(job["duration"])
        session_id = job.get("session_id")
        started_monotonic = float(job["started_monotonic"])

    audio_path: Path | None = None
    try:
        audio_path = _record_pi_audio(duration, job_id=job_id)
        elapsed = int(max(1, round(time.monotonic() - started_monotonic)))
        with PI_RECORD_LOCK:
            job = PI_RECORD_JOBS.get(job_id)
            if job:
                job["status"] = "processing"
                job["elapsed"] = elapsed
                job["proc"] = None
        result = _answer_audio_path(audio_path, min(duration, elapsed), str(session_id or "").strip() or None)
        with PI_RECORD_LOCK:
            job = PI_RECORD_JOBS.get(job_id)
            if job:
                job["status"] = "complete"
                job["result"] = result
                job["completed_at"] = _now()
                job["elapsed"] = elapsed
                job["proc"] = None
                job["audio_path"] = None
    except HTTPException as exc:
        with PI_RECORD_LOCK:
            job = PI_RECORD_JOBS.get(job_id)
            if job:
                job["status"] = "error"
                job["error"] = exc.detail
                job["status_code"] = exc.status_code
                job["completed_at"] = _now()
                job["proc"] = None
                job["audio_path"] = None
    except Exception as exc:
        with PI_RECORD_LOCK:
            job = PI_RECORD_JOBS.get(job_id)
            if job:
                job["status"] = "error"
                job["error"] = str(exc) or exc.__class__.__name__
                job["status_code"] = 500
                job["completed_at"] = _now()
                job["proc"] = None
                job["audio_path"] = None
    finally:
        if audio_path:
            try:
                audio_path.unlink(missing_ok=True)
            except OSError:
                pass


def _start_pi_record_job(duration: int, session_id: str | None = None) -> dict[str, Any]:
    with PI_RECORD_LOCK:
        active = [
            job
            for job in PI_RECORD_JOBS.values()
            if job.get("status") == "recording"
        ]
        if active:
            raise HTTPException(status_code=409, detail="A Raspberry Pi recording is already running")

        _prune_pi_record_jobs_unlocked()
        job_id = uuid4().hex[:12]
        job = {
            "id": job_id,
            "status": "recording",
            "duration": duration,
            "elapsed": 0,
            "session_id": session_id,
            "started_at": _now(),
            "started_monotonic": time.monotonic(),
            "completed_at": None,
            "device": None,
            "stop_requested": False,
            "proc": None,
            "audio_path": None,
            "result": None,
            "error": None,
            "status_code": None,
        }
        PI_RECORD_JOBS[job_id] = job
        thread = threading.Thread(target=_run_pi_record_job, args=(job_id,), daemon=True)
        job["thread"] = thread
        payload = _serialise_pi_record_job(job)
        thread.start()
        return payload


def _stop_pi_record_job(job_id: str) -> dict[str, Any]:
    with PI_RECORD_LOCK:
        job = PI_RECORD_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Pi recording job not found")
        job["stop_requested"] = True
        proc = job.get("proc")
        payload = _serialise_pi_record_job(job)

    if proc and hasattr(proc, "poll") and proc.poll() is None:
        try:
            proc.send_signal(signal.SIGINT)
        except OSError:
            try:
                proc.terminate()
            except OSError:
                pass

    return payload


def _parse_duration(value: Any, default: int = 0) -> int:
    try:
        duration = int(value or default)
    except (TypeError, ValueError):
        duration = default
    if duration < 1 or duration > 300:
        return default
    return duration


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(
        INDEX_FILE.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/call-mode.js", response_class=FileResponse)
async def call_mode_asset() -> FileResponse:
    return FileResponse(
        CALL_MODE_FILE,
        media_type="text/javascript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/app.css", response_class=FileResponse)
async def app_css_asset() -> FileResponse:
    return FileResponse(
        APP_CSS_FILE,
        media_type="text/css; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/ui-motion.js", response_class=FileResponse)
async def ui_motion_asset() -> FileResponse:
    return FileResponse(
        UI_MOTION_FILE,
        media_type="text/javascript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/sessions")
async def sessions() -> dict[str, Any]:
    return {"sessions": _list_sessions()}


@app.post("/api/sessions")
async def create_session(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    session = _create_session(str(body.get("title") or "新会话"))
    return {"session": session, "sessions": _list_sessions()}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    return {"session": _get_session(session_id), "sessions": _list_sessions()}


@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: str, request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    session = _rename_session(session_id, str(body.get("title") or "新会话"))
    return {"session": session, "sessions": _list_sessions()}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    _delete_session(session_id)
    return {"ok": True, "sessions": _list_sessions()}


@app.get("/api/reminders")
async def reminders(request: Request) -> dict[str, Any]:
    include_done = _is_enabled(request.query_params.get("include_done"), default=False)
    return {"reminders": _list_reminders(include_done=include_done)}


@app.post("/api/reminders")
async def create_reminder(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    reminder = _create_reminder(
        str(body.get("text") or ""),
        due_at=str(body.get("due_at") or "").strip() or None,
        due_text=str(body.get("due_text") or "").strip() or None,
        due_precision=str(body.get("due_precision") or "").strip() or None,
    )
    return {"reminder": reminder, "reminders": _list_reminders(include_done=True)}


@app.patch("/api/reminders/{reminder_id}")
async def update_reminder(reminder_id: str, request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    allowed = {key: body[key] for key in ("text", "due_at", "due_text", "due_precision", "done") if key in body}
    reminder = _update_reminder(reminder_id, allowed)
    return {"reminder": reminder, "reminders": _list_reminders(include_done=True)}


@app.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str) -> dict[str, Any]:
    _delete_reminder(reminder_id)
    return {"ok": True, "reminders": _list_reminders(include_done=True)}


@app.post("/api/chat")
async def chat(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    session_id = str(body.get("session_id") or "").strip() or None
    message = str(body.get("message") or "")
    speak = _is_enabled(body.get("speak"), default=False)
    return await asyncio.to_thread(_answer_message, session_id, message, speak=speak, kind="text")


@app.post("/api/respond")
async def respond(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    transcript = str(body.get("transcript") or "")
    duration = _parse_duration(body.get("duration"))
    session_id = str(body.get("session_id") or "").strip() or None
    return await asyncio.to_thread(_answer_transcript, transcript, duration, session_id)


@app.post("/api/converse")
async def converse(
    audio: UploadFile = File(...),
    duration: int = Form(10),
    session_id: str = Form(""),
) -> dict[str, Any]:
    duration = _parse_duration(duration)
    if duration == 0:
        raise HTTPException(status_code=400, detail="duration must be between 1 and 300 seconds")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio.filename or "recording.webm").suffix.lower() or ".webm"
    if suffix not in {".webm", ".ogg", ".wav", ".mp3", ".m4a", ".aac", ".flac"}:
        suffix = ".webm"

    with tempfile.NamedTemporaryFile(prefix="voice_", suffix=suffix, dir=UPLOAD_DIR, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        while chunk := await audio.read(1024 * 1024):
            tmp.write(chunk)

    try:
        return await asyncio.to_thread(_answer_audio_path, tmp_path, duration, session_id.strip() or None)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


@app.post("/api/pi-record")
async def pi_record(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    duration = _parse_duration(body.get("duration"))
    if duration == 0:
        raise HTTPException(status_code=400, detail="duration must be between 1 and 300 seconds")

    session_id = str(body.get("session_id") or "").strip() or None
    return await asyncio.to_thread(_record_and_answer_on_pi, duration, session_id)


@app.post("/api/pi-record/start")
async def pi_record_start(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    duration = _parse_duration(body.get("duration"))
    if duration == 0:
        raise HTTPException(status_code=400, detail="duration must be between 1 and 300 seconds")

    session_id = str(body.get("session_id") or "").strip() or None
    return await asyncio.to_thread(_start_pi_record_job, duration, session_id)


@app.post("/api/pi-record/{job_id}/stop")
async def pi_record_stop(job_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_stop_pi_record_job, job_id)


@app.get("/api/pi-record/{job_id}")
async def pi_record_job(job_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_pi_record_job, job_id)


@app.get("/audio/{path:path}")
async def audio(path: str) -> FileResponse:
    full = (AUDIO_CACHE / path).resolve()
    try:
        full.relative_to(AUDIO_CACHE.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    if not full.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(full)


@app.get("/api/weather")
async def weather(request: Request) -> dict[str, Any]:
    location = str(request.query_params.get("location") or WEATHER_DEFAULT_LOCATION).strip()
    try:
        return await asyncio.to_thread(_weather_payload, location)
    except WeatherLocationRequired as exc:
        raise HTTPException(status_code=400, detail=_weather_location_required_reply()) from exc
    except WeatherLookupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/api/briefing")
async def briefing(request: Request) -> dict[str, Any]:
    location = str(request.query_params.get("location") or WEATHER_DEFAULT_LOCATION).strip()
    return await asyncio.to_thread(_briefing_payload, location or None)


@app.post("/api/pi-playback")
async def pi_playback(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    return await asyncio.to_thread(
        _play_audio_on_pi,
        str(body.get("audio_url") or ""),
        wait=_is_enabled(body.get("wait"), default=False),
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    hermes_cli = _find_hermes_cli()
    tool_status = _agent_tool_status()
    stt = _stt_status()
    tts = _tts_status()
    chat_status = _chat_status()
    pi_record = _pi_record_status()
    pi_playback = _pi_playback_status()
    weather_status = _weather_status()
    briefing_status = _briefing_status()
    reminders_status = _reminders_status()
    return {
        "ok": bool(hermes_cli and tool_status["tts_tool"]),
        "hermes_home": str(HERMES_HOME),
        "hermes_agent": str(HERMES_AGENT),
        "hermes_agent_exists": HERMES_AGENT.exists(),
        "hermes_cli": hermes_cli,
        "chat": chat_status,
        "tools": tool_status,
        "stt": stt,
        "stt_providers": _stt_provider_statuses(),
        "tts": tts,
        "pi_record": pi_record,
        "pi_playback": pi_playback,
        "weather": weather_status,
        "briefing": briefing_status,
        "reminders": reminders_status,
        "sessions_file": str(SESSIONS_FILE),
    }
