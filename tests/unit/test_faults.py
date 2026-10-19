import time

from services.faults import Faults


def test_faults_expire_on_their_own():
    f = Faults()
    f.set("jitter", {"p": 1, "max_ms": 10}, duration_s=0.05)
    assert f.get("jitter") == {"p": 1, "max_ms": 10}
    time.sleep(0.2)  # well past expiry: Windows monotonic() ticks every ~15.6 ms
    assert f.get("jitter") is None and f.snapshot() == {}
