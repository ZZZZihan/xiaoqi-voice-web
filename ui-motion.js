(function exposeXiaoQiUI(globalScope) {
  "use strict";

  const motionQuery =
    typeof globalScope.matchMedia === "function"
      ? globalScope.matchMedia("(prefers-reduced-motion: reduce)")
      : null;
  const activeAnimations = new WeakMap();
  const runningAnimations = new Set();

  function reduceMotion() {
    return Boolean(motionQuery && motionQuery.matches);
  }

  function canAnimate(element) {
    return Boolean(element && typeof element.animate === "function" && !reduceMotion());
  }

  function stop(element, channel = "default") {
    const channels = activeAnimations.get(element);
    const current = channels && channels.get(channel);
    if (current) current.cancel();
  }

  function run(element, keyframes, options = {}, channel = "default") {
    stop(element, channel);
    if (!canAnimate(element)) return null;
    const animation = element.animate(keyframes, {
      duration: 240,
      easing: "cubic-bezier(0.22, 1, 0.36, 1)",
      fill: "backwards",
      ...options,
    });
    let channels = activeAnimations.get(element);
    if (!channels) {
      channels = new Map();
      activeAnimations.set(element, channels);
    }
    channels.set(channel, animation);
    runningAnimations.add(animation);
    const cleanup = () => {
      if (channels.get(channel) === animation) channels.delete(channel);
      runningAnimations.delete(animation);
    };
    animation.addEventListener("finish", cleanup, { once: true });
    animation.addEventListener("cancel", cleanup, { once: true });
    return animation;
  }

  function visualState(element) {
    if (!element || typeof globalScope.getComputedStyle !== "function") {
      return { opacity: "1", transform: "none" };
    }
    const style = globalScope.getComputedStyle(element);
    return {
      opacity: style.opacity || "1",
      transform: style.transform && style.transform !== "none" ? style.transform : "none",
    };
  }

  function fadedOpacity(opacity, factor) {
    const value = Number.parseFloat(opacity);
    return Number.isFinite(value) ? String(Math.max(0, Math.min(1, value * factor))) : opacity;
  }

  function addTransform(transform, delta) {
    return transform && transform !== "none" ? `${transform} ${delta}` : delta;
  }

  function reveal(elements, options = {}) {
    const items = Array.from(elements || []).filter(Boolean);
    const stagger = Math.max(0, Number(options.stagger || 24));
    const fromY = Number(options.fromY ?? 10);
    items.forEach((element, index) => {
      stop(element, "reveal");
      const base = visualState(element);
      run(
        element,
        [
          { opacity: 0, transform: addTransform(base.transform, `translate3d(0, ${fromY}px, 0) scale(0.985)`) },
          { opacity: base.opacity, transform: base.transform },
        ],
        { delay: index * stagger, duration: Number(options.duration || 280) },
        "reveal",
      );
    });
  }

  function bump(element) {
    stop(element, "feedback");
    const base = visualState(element);
    return run(
      element,
      [
        {
          opacity: fadedOpacity(base.opacity, 0.72),
          transform: addTransform(base.transform, "translate3d(0, 2px, 0) scale(0.97)"),
        },
        { opacity: base.opacity, transform: base.transform },
      ],
      { duration: 220 },
      "feedback",
    );
  }

  function morph(element) {
    stop(element, "state");
    const base = visualState(element);
    return run(
      element,
      [
        {
          opacity: fadedOpacity(base.opacity, 0.55),
          transform: addTransform(base.transform, "scale(0.82) rotate(-5deg)"),
        },
        { opacity: base.opacity, transform: base.transform },
      ],
      { duration: 340, easing: "cubic-bezier(0.34, 1.56, 0.64, 1)" },
      "state",
    );
  }

  function bindDetails(root = document) {
    root.querySelectorAll("details").forEach((details) => {
      if (details.dataset.motionBound === "true") return;
      details.dataset.motionBound = "true";
      details.addEventListener("toggle", () => {
        if (!details.open) return;
        const children = Array.from(details.children).slice(1);
        reveal(children, { duration: 230, fromY: -5, stagger: 18 });
      });
    });
  }

  function mount(root = document) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    reveal(root.querySelectorAll(".shell > .side-stack, .shell > .chat-panel, .shell > .sidebar"), {
      duration: 360,
      fromY: 12,
      stagger: 46,
    });
    bindDetails(root);
  }

  if (motionQuery && typeof motionQuery.addEventListener === "function") {
    motionQuery.addEventListener("change", (event) => {
      if (!event.matches) return;
      Array.from(runningAnimations).forEach((animation) => animation.cancel());
    });
  }

  globalScope.XiaoQiUI = Object.freeze({
    bindDetails,
    bump,
    canAnimate,
    mount,
    morph,
    reduceMotion,
    reveal,
    run,
    stop,
  });
})(typeof globalThis !== "undefined" ? globalThis : window);
