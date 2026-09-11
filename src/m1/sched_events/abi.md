# Canonical scheduler event ABI (`struct m1_event`)

One wire format shared by `bpf/sched_collect.bpf.c` → ring buffer →
`collector.decode_record()` → `SchedulerEvent` → raw JSONL.

- Endianness: little-endian (`<` in Python `struct`).
- Alignment: all scalars are 4/8-byte naturally aligned; **no padding**.
- Total size: **84 bytes**.

| field      | C type   | Python type | offset | size |
|------------|----------|-------------|--------|------|
| ts_ns      | `__u64`  | `Q` int     | 0      | 8    |
| cpu        | `__u32`  | `I` int     | 8      | 4    |
| ev         | `__u32`  | `I` int     | 12     | 4    |
| pid        | `__s32`  | `i` int     | 16     | 4    |
| tid        | `__s32`  | `i` int     | 20     | 4    |
| tgid       | `__s32`  | `i` int     | 24     | 4    |
| ppid_unused| `__s32`  | `i` int     | 28     | 4    |
| prio       | `__s32`  | `i` int     | 32     | 4    |
| prev_pid   | `__s32`  | `i` int     | 36     | 4    |
| prev_state | `__s32`  | `i` int     | 40     | 4    |
| next_pid   | `__s32`  | `i` int     | 44     | 4    |
| success    | `__s32`  | `i` int     | 48     | 4    |
| comm       | `char[16]`| `16s` bytes| 52     | 16   |
| next_comm  | `char[16]`| `16s` bytes| 68     | 16   |

Python format: `struct.Struct("<Q I I 9i 16s 16s")`, `size == 84`.

`ev` discriminant: 0=`sched_switch`, 1=`sched_wakeup`, 2=`sched_wakeup_new`,
3=`sched_process_exec`, 4=`sched_process_exit`. Values ≥ 5 are
`events_unknown` (counted, rejected). Buffers shorter than 84 bytes are
`events_malformed` (counted, rejected, never crash). Surplus trailing bytes
are ignored (forward-compatible extension room).

Per-event field validity (all other fields are 0 — the BPF side zeroes every
record because `bpf_ringbuf_reserve` memory is uninitialized):

- `sched_switch`: `cpu, pid/tid (=next_pid), prev_pid, prev_state, next_pid, comm (=next_comm: the switched-in subject task), next_comm`.
- `sched_wakeup` / `sched_wakeup_new`: `cpu (=target_cpu), pid/tid/tgid, prio, success, comm`.
- `sched_process_exec`: `cpu, pid/tid, comm=filename`.
- `sched_process_exit`: `cpu, pid/tid, prio, comm`.
