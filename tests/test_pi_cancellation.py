import pytest

import server


def make_job(monkeypatch, tmp_path, *, stream=True, stopped=False):
    job_id = 'cancel-test'
    audio = tmp_path / 'recording.wav'
    audio.write_bytes(b'audio')
    monkeypatch.setattr(server, 'PI_RECORD_JOBS', {job_id: {
        'id': job_id, 'duration': 5, 'session_id': 'session',
        'started_monotonic': server.time.monotonic(), 'stop_requested': stopped,
        'stream_requested': stream, 'status': 'recording',
    }})
    monkeypatch.setattr(server, '_record_pi_audio', lambda *args, **kwargs: audio)
    return job_id


@pytest.mark.parametrize('streaming_enabled', [True, False])
def test_cancelled_automatic_recording_does_not_transcribe(monkeypatch, tmp_path, streaming_enabled):
    job_id = make_job(monkeypatch, tmp_path, stopped=True)
    monkeypatch.setattr(server, 'STREAMING_VOICE_ENABLED', streaming_enabled)
    def forbidden(*args, **kwargs):
        pytest.fail('cancelled job entered a later stage')
    monkeypatch.setattr(server, '_transcribe_audio', forbidden)
    monkeypatch.setattr(server, '_answer_audio_path', forbidden)
    server._run_pi_record_job(job_id)
    assert server.PI_RECORD_JOBS[job_id]['status'] == 'cancelled'


@pytest.mark.parametrize('streaming_enabled', [True, False])
def test_cancel_during_asr_skips_stream_and_fallback(monkeypatch, tmp_path, streaming_enabled):
    job_id = make_job(monkeypatch, tmp_path)
    monkeypatch.setattr(server, 'STREAMING_VOICE_ENABLED', streaming_enabled)
    def transcribe(path):
        server.PI_RECORD_JOBS[job_id]['stop_requested'] = True
        return {'success': True, 'transcript': '提醒我'}
    monkeypatch.setattr(server, '_transcribe_audio', transcribe)
    monkeypatch.setattr(server, '_stream_voice_answer_for_pi_job', lambda *a, **k: pytest.fail('entered streaming'))
    monkeypatch.setattr(server, '_answer_transcript', lambda *a, **k: pytest.fail('entered fallback'))
    server._run_pi_record_job(job_id)
    assert server.PI_RECORD_JOBS[job_id]['status'] == 'cancelled'


@pytest.mark.parametrize('streaming_enabled', [True, False])
@pytest.mark.parametrize('cancel_at', ['provider', 'tts'])
def test_cancel_during_response_does_not_save(monkeypatch, tmp_path, streaming_enabled, cancel_at):
    job_id = make_job(monkeypatch, tmp_path)
    monkeypatch.setattr(server, 'STREAMING_VOICE_ENABLED', streaming_enabled)
    monkeypatch.setattr(server, '_transcribe_audio', lambda path: {'success': True, 'transcript': '你好'})
    monkeypatch.setattr(server, '_prepare_session', lambda session_id: {'id': session_id, 'messages': []})
    monkeypatch.setattr(server, '_chat_status', lambda: {'provider': 'zai', 'model': 'synthetic-model'})
    monkeypatch.setattr(server, 'DIRECT_HERMES_VOICE', False)
    monkeypatch.setattr(server, '_handle_reminder_intent', lambda text: None)
    monkeypatch.setattr(server, '_build_briefing_context_for_text', lambda text: None)
    monkeypatch.setattr(server, '_build_weather_context_for_text', lambda text: None)
    def provider(prompt):
        if cancel_at == 'provider':
            server.PI_RECORD_JOBS[job_id]['stop_requested'] = True
        return '回复'
    tts_calls = []
    def synthesize(reply):
        tts_calls.append(reply)
        server.PI_RECORD_JOBS[job_id]['stop_requested'] = True
        return {'audio_url': '/audio/synthetic.mp3', 'tts': None}
    monkeypatch.setattr(server, '_run_hermes', provider)
    monkeypatch.setattr(server, '_speak_reply', synthesize)
    monkeypatch.setattr(server, '_append_exchange', lambda *a: pytest.fail('saved cancelled exchange'))
    server._run_pi_record_job(job_id)
    assert server.PI_RECORD_JOBS[job_id]['status'] == 'cancelled'
    assert tts_calls == ([] if cancel_at == 'provider' else ['回复'])
    if streaming_enabled:
        assert server.PI_RECORD_JOBS[job_id]['streaming_fallback'] is True


def test_cancel_before_reminder_skips_side_effect(monkeypatch):
    monkeypatch.setattr(server, '_handle_reminder_intent', lambda *a: pytest.fail('executed reminder'))
    with pytest.raises(server.VoiceJobCancelled):
        list(server._iter_streaming_voice_reply({'messages': []}, '提醒我', is_cancelled=lambda: True))


def test_cancel_during_combine_skips_save(monkeypatch):
    job_id = 'merge-test'
    monkeypatch.setattr(server, 'PI_RECORD_JOBS', {job_id: {'id': job_id, 'stop_requested': False, 'segments': [], 'started_monotonic': server.time.monotonic()}})
    monkeypatch.setattr(server, '_prepare_session', lambda session_id: {'id': session_id, 'messages': []})
    monkeypatch.setattr(server, '_iter_streaming_voice_reply', lambda *a, **k: iter(['你好。']))
    def synthesize(job, text):
        segment = {'sequence': 0, 'text': text, 'audio_url': '/audio/a.mp3'}
        server.PI_RECORD_JOBS[job]['segments'].append(segment)
        return segment
    monkeypatch.setattr(server, '_synthesise_pi_voice_segment', synthesize)
    def combine(segments):
        server.PI_RECORD_JOBS[job_id]['stop_requested'] = True
        return '/audio/a.mp3'
    monkeypatch.setattr(server, '_combine_voice_segments', combine)
    monkeypatch.setattr(server, '_save_voice_exchange', lambda *a, **k: pytest.fail('saved cancelled exchange'))
    with pytest.raises(server.VoiceJobCancelled):
        server._stream_voice_answer_for_pi_job(job_id, '你好', 1, 'session')


def test_manual_stop_still_submits(monkeypatch, tmp_path):
    job_id = make_job(monkeypatch, tmp_path, stream=False, stopped=True)
    answered = []
    def answer(path, duration, session_id):
        answered.append(session_id)
        return {'transcript': '你好', 'reply': '你好'}
    monkeypatch.setattr(server, '_answer_audio_path', answer)
    server._run_pi_record_job(job_id)
    assert answered == ['session']
    assert server.PI_RECORD_JOBS[job_id]['status'] == 'complete'
