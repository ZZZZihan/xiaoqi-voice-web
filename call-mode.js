(function exposeCallMode(globalScope, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (globalScope) {
    globalScope.XiaoQiCallMode = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function buildCallMode() {
  "use strict";

  const CALL_STATES = Object.freeze({
    IDLE: "idle",
    LISTENING: "listening",
    PROCESSING: "processing",
    SPEAKING: "speaking",
    RECOVERING: "recovering",
    ENDED: "ended",
  });

  class CallModeError extends Error {
    constructor(message, code = "call_error", options = {}) {
      super(message);
      this.name = "CallModeError";
      this.code = code;
      this.fatal = Boolean(options.fatal);
      if (options.cause !== undefined) {
        this.cause = options.cause;
      }
    }
  }

  function abortError() {
    const error = new Error("通话已结束");
    error.name = "AbortError";
    error.code = "aborted";
    return error;
  }

  function isAbortError(error) {
    return Boolean(error && (error.name === "AbortError" || error.code === "aborted"));
  }

  function isNoSpeechError(error) {
    if (error && error.code === "no_speech") return true;
    const message = String((error && error.message) || error || "");
    return /no\s+(?:valid\s+)?speech(?:es)?|没有.{0,16}语音|未识别.{0,16}语音|无有效语音/i.test(message);
  }

  function sleep(ms, signal) {
    if (!ms) return Promise.resolve();
    return new Promise((resolve, reject) => {
      if (signal && signal.aborted) {
        reject(abortError());
        return;
      }

      const timeout = setTimeout(() => {
        cleanup();
        resolve();
      }, ms);
      const onAbort = () => {
        clearTimeout(timeout);
        cleanup();
        reject(abortError());
      };
      const cleanup = () => {
        if (signal) signal.removeEventListener("abort", onAbort);
      };
      if (signal) signal.addEventListener("abort", onAbort, { once: true });
    });
  }

  function createCallController(options = {}) {
    const captureTurn = options.captureTurn;
    const processTurn = options.processTurn;
    const playReply = options.playReply;
    if (typeof captureTurn !== "function") throw new TypeError("captureTurn 必须是函数");
    if (typeof processTurn !== "function") throw new TypeError("processTurn 必须是函数");
    if (typeof playReply !== "function") throw new TypeError("playReply 必须是函数");

    const onStateChange = typeof options.onStateChange === "function" ? options.onStateChange : () => {};
    const onError = typeof options.onError === "function" ? options.onError : () => {};
    const wait = typeof options.sleep === "function" ? options.sleep : sleep;
    const retryDelayMs = Math.max(0, Number(options.retryDelayMs ?? 900));
    const noSpeechDelayMs = Math.max(0, Number(options.noSpeechDelayMs ?? 300));
    const maxConsecutiveErrors = Math.max(1, Number(options.maxConsecutiveErrors ?? 3));

    let currentState = CALL_STATES.IDLE;
    let active = false;
    let consecutiveErrors = 0;
    let generation = 0;
    let runPromise = Promise.resolve(CALL_STATES.IDLE);
    let runAbortController = null;

    function notify(callback, payload) {
      try {
        callback(payload);
      } catch {
        // UI observers must not be able to break the call loop.
      }
    }

    function transition(nextState, detail = {}) {
      currentState = nextState;
      notify(onStateChange, {
        state: nextState,
        active,
        consecutiveErrors,
        ...detail,
      });
    }

    function assertCurrent(runGeneration, signal) {
      if (!active || generation !== runGeneration || signal.aborted) {
        throw abortError();
      }
    }

    async function runLoop(runGeneration, signal) {
      while (active && generation === runGeneration && !signal.aborted) {
        try {
          transition(CALL_STATES.LISTENING);
          const turn = await captureTurn({ signal });
          assertCurrent(runGeneration, signal);
          if (!turn) {
            throw new CallModeError("没有检测到语音", "no_speech");
          }

          transition(CALL_STATES.PROCESSING);
          const reply = await processTurn(turn, { signal });
          assertCurrent(runGeneration, signal);

          transition(CALL_STATES.SPEAKING);
          await playReply(reply, { signal });
          assertCurrent(runGeneration, signal);
          consecutiveErrors = 0;
        } catch (error) {
          if (isAbortError(error) || !active || generation !== runGeneration || signal.aborted) {
            break;
          }

          let callError =
            error instanceof CallModeError
              ? error
              : new CallModeError(error && error.message ? error.message : "电话模式发生未知错误", "call_error", {
                  cause: error,
                });
          const noSpeech = isNoSpeechError(callError);
          if (noSpeech && callError.code !== "no_speech") {
            callError = new CallModeError("没有听到清晰语音", "no_speech", { cause: callError });
          }
          if (!noSpeech) consecutiveErrors += 1;

          notify(onError, {
            error: callError,
            code: callError.code,
            fatal: callError.fatal,
            consecutiveErrors,
          });

          if (callError.fatal || (!noSpeech && consecutiveErrors >= maxConsecutiveErrors)) {
            active = false;
            transition(CALL_STATES.ENDED, {
              reason: callError.fatal ? "fatal_error" : "error_limit",
              error: callError,
            });
            break;
          }

          transition(CALL_STATES.RECOVERING, {
            reason: noSpeech ? "no_speech" : "retryable_error",
            error: callError,
          });
          try {
            await wait(noSpeech ? noSpeechDelayMs : retryDelayMs, signal);
          } catch (waitError) {
            if (!isAbortError(waitError)) throw waitError;
            break;
          }
        }
      }

      return currentState;
    }

    function start() {
      if (active) return runPromise;

      active = true;
      consecutiveErrors = 0;
      generation += 1;
      const runGeneration = generation;
      runAbortController = new AbortController();
      runPromise = runLoop(runGeneration, runAbortController.signal).finally(() => {
        if (generation === runGeneration) {
          runAbortController = null;
          if (active) {
            active = false;
            transition(CALL_STATES.ENDED, { reason: "loop_finished" });
          }
        }
      });
      return runPromise;
    }

    function hangUp(reason = "user") {
      if (!active) {
        if (currentState !== CALL_STATES.ENDED) {
          transition(CALL_STATES.ENDED, { reason });
        }
        return;
      }

      active = false;
      generation += 1;
      if (runAbortController) runAbortController.abort();
      transition(CALL_STATES.ENDED, { reason });
    }

    return Object.freeze({
      getConsecutiveErrors: () => consecutiveErrors,
      getState: () => currentState,
      hangUp,
      isActive: () => active,
      start,
    });
  }

  return Object.freeze({
    CALL_STATES,
    CallModeError,
    createCallController,
    isAbortError,
    isNoSpeechError,
  });
});
