"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { CALL_STATES, CallModeError, createCallController, isNoSpeechError } = require("../call-mode.js");

test("a successful turn listens, processes, speaks, and can hang up", async () => {
  const states = [];
  const calls = [];
  let controller;
  controller = createCallController({
    captureTurn: async () => {
      calls.push("capture");
      return { kind: "transcript", transcript: "你好" };
    },
    processTurn: async (turn) => {
      calls.push(`process:${turn.transcript}`);
      return { audio_url: "/audio/reply.ogg" };
    },
    playReply: async (reply) => {
      calls.push(`play:${reply.audio_url}`);
      controller.hangUp("test_complete");
    },
    onStateChange: ({ state }) => states.push(state),
  });

  await controller.start();

  assert.deepEqual(calls, ["capture", "process:你好", "play:/audio/reply.ogg"]);
  assert.deepEqual(states, [CALL_STATES.LISTENING, CALL_STATES.PROCESSING, CALL_STATES.SPEAKING, CALL_STATES.ENDED]);
  assert.equal(controller.isActive(), false);
  assert.equal(controller.getState(), CALL_STATES.ENDED);
});

test("no speech retries without consuming the consecutive error budget", async () => {
  const states = [];
  let captureCount = 0;
  let controller;
  controller = createCallController({
    captureTurn: async () => {
      captureCount += 1;
      if (captureCount === 1) throw new CallModeError("没有听到语音", "no_speech");
      return { kind: "transcript", transcript: "第二次听到了" };
    },
    processTurn: async () => ({ audio_url: "/audio/reply.ogg" }),
    playReply: async () => controller.hangUp("test_complete"),
    sleep: async () => {},
    onStateChange: ({ state }) => states.push(state),
  });

  await controller.start();

  assert.equal(captureCount, 2);
  assert.equal(controller.getConsecutiveErrors(), 0);
  assert.ok(states.includes(CALL_STATES.RECOVERING));
  assert.equal(states.at(-1), CALL_STATES.ENDED);
});

test("Volcengine empty-audio errors are classified as no speech", async () => {
  assert.equal(
    isNoSpeechError(
      new Error(
        'Volcengine ASR failed: {"code": 1013, "message": "No valid speeches found in input audio"}',
      ),
    ),
    true,
  );

  let processingAttempts = 0;
  let controller;
  controller = createCallController({
    captureTurn: async () => ({ kind: "audio" }),
    processTurn: async () => {
      processingAttempts += 1;
      if (processingAttempts === 1) {
        throw new Error("No valid speeches found in input audio");
      }
      return { audio_url: "/audio/reply.ogg" };
    },
    playReply: async () => controller.hangUp("test_complete"),
    sleep: async () => {},
  });

  await controller.start();

  assert.equal(processingAttempts, 2);
  assert.equal(controller.getConsecutiveErrors(), 0);
});

test("three consecutive processing errors end the call", async () => {
  const states = [];
  let processingAttempts = 0;
  const controller = createCallController({
    captureTurn: async () => ({ kind: "transcript", transcript: "测试" }),
    processTurn: async () => {
      processingAttempts += 1;
      throw new Error("模型暂时不可用");
    },
    playReply: async () => {
      throw new Error("should not be reached");
    },
    maxConsecutiveErrors: 3,
    sleep: async () => {},
    onStateChange: ({ state }) => states.push(state),
  });

  await controller.start();

  assert.equal(processingAttempts, 3);
  assert.equal(controller.getConsecutiveErrors(), 3);
  assert.equal(states.filter((state) => state === CALL_STATES.RECOVERING).length, 2);
  assert.equal(states.at(-1), CALL_STATES.ENDED);
});

test("a fatal microphone permission error ends immediately", async () => {
  let captureAttempts = 0;
  const controller = createCallController({
    captureTurn: async () => {
      captureAttempts += 1;
      throw new CallModeError("权限被拒绝", "permission_denied", { fatal: true });
    },
    processTurn: async () => ({}),
    playReply: async () => {},
    sleep: async () => {},
  });

  await controller.start();

  assert.equal(captureAttempts, 1);
  assert.equal(controller.getState(), CALL_STATES.ENDED);
  assert.equal(controller.isActive(), false);
});

test("hang up aborts an in-flight listening turn", async () => {
  let signalWasAborted = false;
  let announceListening;
  const listening = new Promise((resolve) => {
    announceListening = resolve;
  });
  const controller = createCallController({
    captureTurn: ({ signal }) =>
      new Promise((resolve, reject) => {
        announceListening();
        signal.addEventListener(
          "abort",
          () => {
            signalWasAborted = true;
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          },
          { once: true },
        );
      }),
    processTurn: async () => ({}),
    playReply: async () => {},
  });

  const run = controller.start();
  await listening;
  controller.hangUp("user");
  await run;

  assert.equal(signalWasAborted, true);
  assert.equal(controller.getState(), CALL_STATES.ENDED);
  assert.equal(controller.isActive(), false);
});
