"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const { CallModeError, createCallController } = require("../call-mode.js");

// Exercise the browser adapters themselves, with all media and network I/O stubbed.
const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const adapterNames = [
  "stopPiCallJob", "piCallJobFinished", "drainPiCallJob", "capturePiCallTurn",
  "piStreamingSegments", "playPiStreamingReply",
];
const adapterSource = adapterNames.map((name) => {
  const declaration = new RegExp(`^      (?:async )?function ${name}\\(`, "m").exec(html);
  assert.ok(declaration, `Missing browser adapter ${name}`);
  const end = html.indexOf("\n      }", declaration.index);
  assert.notEqual(end, -1, `Missing closing brace for ${name}`);
  return html.slice(declaration.index, end + "\n      }".length);
}).join("\n");

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function streamingData() {
  return {
    stream_job_id: "synthetic-job",
    transcript: "测试",
    initial_job: {
      status: "streaming",
      segments: [{ sequence: 0, audio_url: "/audio/synthetic-0.mp3" }],
    },
  };
}

function harness(overrides = {}) {
  const calls = { stops: [], polls: [], played: [], sessions: [] };
  let now = 0;
  const context = {
    AbortController, DOMException, setTimeout, clearTimeout,
    Date: { now: () => now },
    state: { playTarget: "browser" },
    els: { bar: { style: {} }, callState: {}, transcriptPreview: {} },
    callAudio: {}, Audio: function () {}, callSessionId: "synthetic-session",
    canUsePiRecord: () => true,
    piCallTurnDuration: () => 8,
    piCallEndpointSummary: () => "synthetic endpoint",
    setVoiceStatus() {},
    callError: (message, code, options) => new CallModeError(message, code, options),
    applySessionPayload: (result) => calls.sessions.push(result),
    fetch: async (url, options) => {
      calls.stops.push({ url, options });
      return { ok: true };
    },
    requestJSON: async (url) => {
      calls.polls.push(url);
      return url.endsWith("/start") ? { job_id: "synthetic-job" } : { status: "cancelled" };
    },
    playAudio: async (url) => calls.played.push(url),
    waitForCallPoll: async (ms, signal) => {
      if (signal.aborted) throw new DOMException("aborted", "AbortError");
      now += ms;
    },
    ...overrides,
  };
  vm.createContext(context);
  vm.runInContext(adapterSource, context, { filename: "index.html adapters" });
  return { context, calls };
}

for (const failurePoint of ["playback", "stream poll", "capture poll"]) {
  test(`${failurePoint} failure awaits one stop request and terminal job state`, async () => {
    const failure = new Error(`synthetic ${failurePoint} failure`);
    const stopStarted = deferred();
    const stopResponse = deferred();
    const drainStarted = deferred();
    const terminalJob = deferred();
    let pollCount = 0;
    const { context, calls } = harness();
    context.fetch = async (url, options) => {
      calls.stops.push({ url, options });
      stopStarted.resolve();
      return stopResponse.promise;
    };
    context.requestJSON = async (url) => {
      if (url.endsWith("/start")) return { job_id: "synthetic-job" };
      if (failurePoint !== "playback" && pollCount++ === 0) throw failure;
      drainStarted.resolve();
      return terminalJob.promise;
    };
    if (failurePoint === "playback") context.playAudio = async () => { throw failure; };
    const signal = new AbortController().signal;
    const run = failurePoint === "capture poll"
      ? context.capturePiCallTurn({ signal })
      : context.playPiStreamingReply(streamingData(), { signal });
    let settled = false;
    const outcome = assert.rejects(run, (error) => error === failure).then(() => { settled = true; });
    await stopStarted.promise;
    assert.equal(settled, false);
    assert.equal(calls.stops.length, 1);
    assert.equal(calls.stops[0].options.method, "POST");
    assert.equal(calls.stops[0].options.keepalive, true);
    assert.equal(calls.stops[0].options.signal.aborted, false);
    stopResponse.resolve({ ok: true });
    await drainStarted.promise;
    assert.equal(settled, false, "Recovery must wait until the old worker is terminal");
    terminalJob.resolve({ status: "cancelled" });
    await outcome;
    assert.equal(calls.stops.length, 1);
    assert.equal(signal.aborted, false);
  });
}

test("capture hands a ready stream to playback without stopping it", async () => {
  const data = streamingData();
  const { context, calls } = harness({
    requestJSON: async (url) => url.endsWith("/start")
      ? { job_id: data.stream_job_id }
      : { ...data.initial_job, stream_requested: true, transcript: data.transcript },
  });
  const controller = new AbortController();
  const turn = await context.capturePiCallTurn({ signal: controller.signal });
  assert.equal(turn.kind, "pi_stream");
  assert.equal(turn.data.stream_job_id, data.stream_job_id);
  assert.equal(calls.stops.length, 0);
  controller.abort();
  assert.equal(calls.stops.length, 0, "Capture removed its abort listener after handoff");
});

test("completed nonstreaming capture needs no cleanup request", async () => {
  const { context, calls } = harness({
    requestJSON: async (url) => url.endsWith("/start")
      ? { job_id: "synthetic-job" }
      : { status: "complete", result: { transcript: "测试", audio_url: "/audio/full.mp3" } },
  });
  const turn = await context.capturePiCallTurn({ signal: new AbortController().signal });
  assert.equal(turn.kind, "pi_reply");
  assert.equal(calls.stops.length, 0);
});

test("stream playback keeps segment order, skips repeats, and applies completed session", async () => {
  const data = streamingData();
  const result = { transcript: "完整转写", session: { id: "synthetic-session" } };
  const { context, calls } = harness({
    requestJSON: async () => ({
      status: "complete", result,
      segments: [
        { sequence: 2, audio_url: "/audio/synthetic-2.mp3" },
        ...data.initial_job.segments,
        { sequence: 1, audio_url: "/audio/synthetic-1.mp3" },
      ],
    }),
  });
  const controller = new AbortController();
  assert.equal(await context.playPiStreamingReply(data, { signal: controller.signal }), result);
  assert.deepEqual(calls.played, ["/audio/synthetic-0.mp3", "/audio/synthetic-1.mp3", "/audio/synthetic-2.mp3"]);
  assert.deepEqual(calls.sessions, [result]);
  assert.equal(context.els.transcriptPreview.textContent, result.transcript);
  controller.abort();
  assert.equal(calls.stops.length, 0);
});

for (const adapter of ["capture", "playback"]) {
  test(`hangup during ${adapter} requests stop once and skips terminal drain`, async () => {
    const entered = deferred();
    const { context, calls } = harness();
    const waitForAbort = (signal) => new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      entered.resolve();
    });
    context.requestJSON = async (url, { signal }) => {
      if (url.endsWith("/start")) return { job_id: "synthetic-job" };
      calls.polls.push(url);
      assert.equal(adapter, "capture", "Hangup must not poll to drain playback");
      return waitForAbort(signal);
    };
    context.playAudio = async (url, { signal }) => waitForAbort(signal);
    const controller = new AbortController();
    const run = adapter === "capture"
      ? context.capturePiCallTurn({ signal: controller.signal })
      : context.playPiStreamingReply(streamingData(), { signal: controller.signal });
    const outcome = assert.rejects(run, { name: "AbortError" });
    await entered.promise;
    controller.abort();
    await outcome;
    assert.equal(calls.stops.length, 1);
    assert.equal(calls.polls.length, adapter === "capture" ? 1 : 0);
  });
}

test("already-aborted playback stops the unfinished job once without playing", async () => {
  const { context, calls } = harness();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(context.playPiStreamingReply(streamingData(), { signal: controller.signal }), { name: "AbortError" });
  assert.equal(calls.stops.length, 1);
  assert.deepEqual(calls.played, []);
  assert.deepEqual(calls.polls, []);
});

test("hangup releases recovery while its stop request is still pending", { timeout: 1000 }, async () => {
  const failure = new Error("synthetic playback failure");
  const stopStarted = deferred();
  const stopResponse = deferred();
  const { context, calls } = harness({
    playAudio: async () => { throw failure; },
  });
  context.fetch = async (url) => {
    calls.stops.push(url);
    stopStarted.resolve();
    return stopResponse.promise;
  };
  const controller = new AbortController();
  const outcome = assert.rejects(
    context.playPiStreamingReply(streamingData(), { signal: controller.signal }),
    (error) => error === failure,
  );
  try {
    await stopStarted.promise;
    controller.abort();
    await outcome;
    assert.equal(calls.stops.length, 1);
    assert.deepEqual(calls.polls, []);
  } finally {
    stopResponse.resolve({ ok: true });
  }
});

test("a pruned job is already settled and preserves the original failure", async () => {
  const failure = new Error("synthetic playback failure");
  const { context, calls } = harness({
    playAudio: async () => { throw failure; },
    requestJSON: async () => { throw Object.assign(new Error("not found"), { status: 404 }); },
  });
  await assert.rejects(
    context.playPiStreamingReply(streamingData(), { signal: new AbortController().signal }),
    (error) => error === failure,
  );
  assert.equal(calls.stops.length, 1);
});

test("automatic retry cannot start until the cancelled worker is terminal", async () => {
  const failure = new Error("synthetic playback failure");
  let oldJobActive = true;
  let polls = 0;
  const { context } = harness({
    playAudio: async () => { throw failure; },
    requestJSON: async () => {
      if (++polls === 1) return { status: "streaming", stop_requested: true };
      oldJobActive = false;
      return { status: "cancelled" };
    },
  });
  let captures = 0;
  let controller;
  controller = createCallController({
    captureTurn: async () => {
      if (++captures === 1) return streamingData();
      assert.equal(oldJobActive, false, "The previous worker would reject this capture with HTTP 409");
      controller.hangUp("test_complete");
      return {};
    },
    processTurn: async (turn) => turn,
    playReply: context.playPiStreamingReply,
    sleep: async () => {},
  });
  await controller.start();
  assert.equal(captures, 2);
  assert.equal(polls, 2);
});

for (const unavailable of [false, true]) {
  test(`unsettled cleanup ends the call without another capture${unavailable ? " when offline" : ""}`, async () => {
    const { context, calls } = harness({
      playAudio: async () => { throw new Error("synthetic playback failure"); },
      requestJSON: async () => {
        if (unavailable) throw new Error("synthetic network failure");
        return { status: "streaming" };
      },
    });
    let captures = 0;
    const errors = [];
    const controller = createCallController({
      captureTurn: async () => { captures += 1; return streamingData(); },
      processTurn: async (turn) => turn,
      playReply: context.playPiStreamingReply,
      onError: ({ error }) => errors.push(error),
      sleep: async () => {},
    });
    await controller.start();
    assert.equal(captures, 1);
    assert.equal(calls.stops.length, 1);
    assert.equal(errors.length, 1);
    assert.equal(errors[0].code, "pi_job_cleanup_failed");
    assert.equal(errors[0].fatal, true);
    assert.equal(controller.isActive(), false);
  });
}
