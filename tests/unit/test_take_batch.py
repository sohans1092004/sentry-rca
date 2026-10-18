from processors.runner import CHUNK_MESSAGES, take_batch


class Msg:
    def __init__(self, n):
        self.n = n

    def value(self):
        return b"x" * self.n


class FakeConsumer:
    def __init__(self, sizes):
        self.queue = [Msg(n) for n in sizes]
        self.calls = []

    def consume(self, num_messages, timeout):
        self.calls.append(num_messages)
        out, self.queue = self.queue[:num_messages], self.queue[num_messages:]
        return out


def test_batch_is_bounded_by_bytes_not_message_count():
    c = FakeConsumer([1_000_000] * 500)  # a backlog of big OTLP messages
    batch = take_batch(c, max_bytes=2_000_000, wait_s=5)
    assert len(batch) == CHUNK_MESSAGES  # overshoot is at most one chunk
    assert all(n <= CHUNK_MESSAGES for n in c.calls)


def test_small_messages_fill_the_byte_budget_then_stop():
    c = FakeConsumer([1_000] * 5_000)
    batch = take_batch(c, max_bytes=100_000, wait_s=5)
    assert sum(len(m.value()) for m in batch) == 100_000 and len(c.queue) == 4_900


def test_returns_what_arrived_when_the_topic_goes_quiet():
    c = FakeConsumer([10, 20, 30])
    assert len(take_batch(c, max_bytes=10_000, wait_s=5)) == 3
