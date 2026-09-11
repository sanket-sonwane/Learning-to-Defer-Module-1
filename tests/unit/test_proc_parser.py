"""Unit: /proc stat/status/io parsing, incl. comm with spaces/parens."""
from m1.task_discovery import proc_parser

def _stat_line(pid: int = 1234, comm: str = "my app (test)") -> str:
    # 50 post-comm tokens matching proc(5) order:
    # state, ppid, pgrp, session, tty_nr, tpgid, flags, minflt, cminflt, majflt,
    # cmajflt, utime, stime, cutime, cstime, priority, nice, num_threads,
    # itrealvalue, starttime, vsize, rss, ... processor at index 36.
    toks = ["0"] * 50
    toks[0] = "S"
    toks[1] = "1"
    toks[11] = "50"      # utime
    toks[12] = "30"      # stime
    toks[15] = "20"      # priority
    toks[16] = "0"       # nice
    toks[17] = "4"       # num_threads
    toks[19] = "999999"  # starttime
    toks[20] = "1000000"  # vsize
    toks[21] = "200"     # rss
    toks[36] = "2"       # processor
    return f"{pid} ({comm}) " + " ".join(toks)


STAT = _stat_line()


def test_stat_comm_with_spaces_and_parens():
    d = proc_parser.parse_stat_text(STAT)
    assert d["pid"] == 1234
    assert d["comm"] == "my app (test)"
    assert d["state"] == "S"
    assert d["ppid"] == 1
    assert d["priority"] == 20
    assert d["nice"] == 0
    assert d["num_threads"] == 4
    assert d["starttime"] == 999999
    assert d["utime"] == 50
    assert d["stime"] == 30
    assert d["processor"] == 2


def test_stat_short_raises():
    import pytest
    with pytest.raises(ValueError):
        proc_parser.parse_stat_text("1 (x) R")


def test_status_parse():
    txt = ("Name:\tpython3\nTGID:\t1234\nState:\tR (running)\n"
           "VmRSS:\t  12345 kB\nvoluntary_ctxt_switches:\t10\n"
           "nonvoluntary_ctxt_switches:\t3\n")
    d = proc_parser.parse_status_text(txt)
    assert d["voluntary_ctxt_switches"] == 10
    assert d["nonvoluntary_ctxt_switches"] == 3
    assert d["VmRSS_kb"] == 12345
    assert d["TGID"] == 1234


def test_io_parse():
    txt = "rchar: 100\nwchar: 200\nread_bytes: 300\nwrite_bytes: 400\nsyscr: 5\n"
    d = proc_parser.parse_io_text(txt)
    assert d["read_bytes"] == 300 and d["write_bytes"] == 400
    assert d["rchar"] == 100
