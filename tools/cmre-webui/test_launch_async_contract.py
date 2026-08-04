#!/usr/bin/env python3
"""回归测试：异步 launcher 失败时先保留真实输出，再记录退出码。"""

from collections import deque
import io
import threading

import server


class _FinishedProcess:
    def wait(self):
        return 4294967295


def test_launcher_failure_preserves_pipe_output_before_exit_code():
    with server._log_lock:
        previous = list(server._log_lines)
        server._log_lines.clear()
    try:
        output_tail = {"stdout": deque(maxlen=80), "stderr": deque(maxlen=80)}
        tail_lock = threading.Lock()
        readers = [
            threading.Thread(
                target=server._read_pipe,
                args=(io.StringIO("staging started\n"), ""),
                kwargs={"output_tail": output_tail, "tail_lock": tail_lock, "stream_name": "stdout"},
            ),
            threading.Thread(
                target=server._read_pipe,
                args=(io.StringIO("SwarmStory campaign not found\n"), "[stderr] "),
                kwargs={"output_tail": output_tail, "tail_lock": tail_lock, "stream_name": "stderr"},
            ),
        ]
        for reader in readers:
            reader.start()
        server._wait_for_process(_FinishedProcess(), readers, output_tail, tail_lock)

        with server._log_lock:
            fresh = list(server._log_lines)
        error_index = next(i for i, line in enumerate(fresh) if "SwarmStory campaign not found" in line)
        exit_index = next(i for i, line in enumerate(fresh) if "launcher 进程结束" in line)
        assert error_index < exit_index
        assert "exit=4294967295 (signed=-1)" in fresh[exit_index]
    finally:
        with server._log_lock:
            server._log_lines[:] = previous
