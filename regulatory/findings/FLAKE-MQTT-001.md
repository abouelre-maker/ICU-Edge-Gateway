# FLAKE-MQTT-001 — Contention-Sensitive Test on the Store-and-Forward Requeue Path

**Status:** 🔍 **OPEN — TRACKED, NOT FIXED**
**Raised:** 2026-08-21
**Priority:** Low urgency, but **do not close by loosening the assertion.**

## The test

```
tests/unit/test_mqtt_publisher.py::TestRunLoopRequeueOnFailure::test_failed_item_is_requeued_not_dropped
```

## What was observed

During Phase 6 live verification the full suite failed once on this test:

```
1 failed, 815 passed, 1 xfailed
```

At that moment the machine was running, concurrently: the gateway (uvicorn),
the 3-bed MLLP streamer, a Streamlit dashboard re-rendering on a timer, and a
Chrome instance driving browser automation.

## What was then established

| Check | Result |
|---|---|
| Same test in isolation | passed |
| `test_mqtt_publisher.py` alone, ×3 | 14/14 passed each time |
| Full suite, ×3 consecutive, machine quiet | 816 passed, 1 xfailed each time |
| Touched by the current branch? | **No.** `git status` clean for both `mqtt_publisher.py` and its test; last change was commit `567c4bc` (HAZARD-DSP-007 serialization guard), which the test passed under repeatedly afterwards |

So: **not a regression from Phase 5/6 work**, and not reproducible on an idle
machine.

## Why this is worth keeping open

The test guards a genuinely safety-relevant property. `StoreAndForwardRingBuffer`
exists because telemetry must survive a WAN outage
(ISO 14971 **HAZARD-STREAM-002**), and `requeue_front()` is what ensures a
*failed delivery* is retried ahead of newer data rather than dropped. A test
covering "a failed item is requeued, not dropped" is exactly the test one
would least like to see become unreliable.

Two possibilities, and they have opposite implications:

1. **The test is timing-fragile** — it awaits a background task or sleeps for
   a fixed interval, and CPU starvation makes that interval insufficient.
   Benign; the fix is to make the test wait on a condition rather than a
   duration.
2. **The publisher's run loop is itself timing-sensitive** under contention,
   and the test is correctly reporting a real narrow window in which a failed
   item could be dropped rather than requeued. That would be a genuine defect
   on a data-loss path.

**These cannot be distinguished without looking.** The observation alone does
not tell us which it is.

## Explicitly NOT the fix

- Do **not** widen a timeout or loosen an assertion to make it green. That
  converts possibility (2) into a silent, permanent defect and destroys the
  only signal pointing at it.
- Do **not** mark it `xfail` or `skip`.
- Do **not** add a retry decorator.

Any of those would trade a visible intermittent failure for an invisible
constant one, on a path whose whole purpose is not losing clinical telemetry.

## Suggested investigation

1. Read the test and determine whether it synchronises on a condition or on
   elapsed time.
2. Reproduce deliberately under load — e.g. run the suite pinned to a single
   CPU, or with a competing busy loop — rather than waiting to see it again.
3. If it is (1), rewrite the wait as an event/condition and note that the
   production code was exonerated.
4. If it is (2), raise a hazard entry against the requeue path and treat it
   as a data-loss defect, not a test defect.

## Provenance

Recorded during Phase 6 rather than ignored, because a flaky test on a
store-and-forward requeue path is worth understanding properly and later, on
its own — not patched over in passing while doing unrelated work.

No code, test or configuration has been changed in response to this
observation.
