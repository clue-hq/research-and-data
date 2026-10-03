"""Bounded media readiness for temporary screenshot pages, not source mutation."""

from typing import Any

_MEDIA_READINESS = r"""
async ({timeoutMs, maxSteps}) => {
  const deadline = performance.now() + timeoutMs;
  const original = {x: window.scrollX, y: window.scrollY};
  const decoding = new Map();
  const visibleImages = () => Array.from(document.images).filter(img => {
    const rect = img.getBoundingClientRect();
    const style = getComputedStyle(img);
    if (!(rect.width > 0 && rect.height > 0) || style.visibility === 'hidden'
        || style.display === 'none') return false;
    // An inactive slide can have dimensions while being entirely clipped. Its
    // lazy image is not part of this capture, unlike visible media below the fold.
    let {left, right, top, bottom} = rect;
    for (let parent = img.parentElement; parent && parent !== document.body
         && parent !== document.documentElement; parent = parent.parentElement) {
      const box = parent.getBoundingClientRect();
      const clip = getComputedStyle(parent);
      if (clip.overflowX !== 'visible') {
        left = Math.max(left, box.left); right = Math.min(right, box.right);
      }
      if (clip.overflowY !== 'visible') {
        top = Math.max(top, box.top); bottom = Math.min(bottom, box.bottom);
      }
      if (right <= left || bottom <= top) return false;
    }
    return true;
  });
  const pause = () => new Promise(resolve => setTimeout(resolve, 25));
  const status = img => {
    if (!img.complete) return 'loading';
    if (!img.naturalWidth) return 'load_failed';
    if (!decoding.has(img)) {
      decoding.set(img, 'decoding');
      img.decode().then(() => decoding.set(img, 'ready'), () => decoding.set(img, 'decode_failed'));
    }
    return decoding.get(img);
  };
  let coverageComplete = false;
  let steps = 0;
  try {
    // A full-page screenshot does not make native lazy images enter the viewport.
    // Walk at the current width; do not force eager loading or change source styles.
    for (; steps < maxSteps && performance.now() < deadline; steps++) {
      const end = Math.max(0, document.documentElement.scrollHeight - innerHeight);
      const y = Math.min(steps * Math.max(1, innerHeight * 0.8), end);
      window.scrollTo({left: original.x, top: y, behavior: 'instant'});
      await pause();
      visibleImages().forEach(status);
      if (y >= end) { coverageComplete = true; break; }
    }
    while (performance.now() < deadline) {
      const states = visibleImages().map(status);
      if (states.every(value => !['loading', 'decoding'].includes(value))) break;
      await pause();
    }
  } finally {
    window.scrollTo({left: original.x, top: original.y, behavior: 'instant'});
  }
  const images = visibleImages();
  const unresolved = images.map((img, index) => ({
    index, source: (img.currentSrc || img.getAttribute('src') || '').slice(0, 500),
    reason: status(img)
  })).filter(item => item.reason !== 'ready');
  const restored = window.scrollX === original.x && window.scrollY === original.y;
  return {
    settled: coverageComplete && unresolved.length === 0 && restored,
    coverage_complete: coverageComplete,
    images_checked: images.length,
    unresolved,
    timed_out: performance.now() >= deadline,
    scroll_restored: restored
  };
}
"""


def prepare_capture_media(page: Any, *, timeout_ms: int = 5_000, max_steps: int = 80) -> dict:
    """Warm native lazy media and wait for decode under one deadline.

    Does not pause animations, synthesize UI interactions, replace failed media or
    certify video playback. Each width/reduced-motion context remains independent.
    """
    try:
        result = page.evaluate(_MEDIA_READINESS, {"timeoutMs": timeout_ms, "maxSteps": max_steps})
        if isinstance(result, dict):
            return result
    except Exception:  # A missing observation is never a successful media check.
        pass
    return {
        "settled": False,
        "coverage_complete": False,
        "unresolved": [],
        "error": "media_readiness_unobserved",
    }
