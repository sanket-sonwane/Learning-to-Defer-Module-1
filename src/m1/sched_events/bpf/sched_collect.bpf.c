// sched_collect.bpf.c — libbpf CO-RE scheduler event collector (M1.3).
//
// Collects:
//   - sched_switch
//   - sched_wakeup
//   - sched_wakeup_new
//   - sched_process_exec
//   - sched_process_exit
//
// Kernel -> userspace transport:
//   BPF ring buffer
//
// Wire ABI:
//   struct m1_event MUST remain exactly 84 bytes.
//
// Python decoder ABI:
//   <Q I I 9i 16s 16s
//
// M1 deliberately does NOT use sched_ext.
//
// License: GPL
//

#include "vmlinux.h"

#include <bpf/bpf_helpers.h>

#define TASK_COMM_LEN 16


/*
 * --------------------------------------------------------------------------
 * Event identifiers
 * --------------------------------------------------------------------------
 *
 * Must match:
 *   - collector.py
 *   - abi.md
 *   - Python decoder
 */
enum m1_ev {
    EV_SWITCH     = 0,
    EV_WAKEUP     = 1,
    EV_WAKEUP_NEW = 2,
    EV_EXEC       = 3,
    EV_EXIT       = 4,
};


/*
 * --------------------------------------------------------------------------
 * Canonical 84-byte userspace wire record
 * --------------------------------------------------------------------------
 *
 * Python format:
 *
 *     <Q I I 9i 16s 16s
 *
 * Field layout:
 *
 *     0   : u64 ts_ns
 *     8   : u32 cpu
 *     12  : u32 ev
 *     16  : s32 pid
 *     20  : s32 tid
 *     24  : s32 tgid
 *     28  : s32 ppid_unused
 *     32  : s32 prio
 *     36  : s32 prev_pid
 *     40  : s32 prev_state
 *     44  : s32 next_pid
 *     48  : s32 success
 *     52  : char comm[16]
 *     68  : char next_comm[16]
 *
 * Total = 84 bytes.
 *
 * The structure is explicitly packed because otherwise C may add tail
 * padding and produce an 88-byte structure.
 */
struct __attribute__((packed)) m1_event {
    __u64 ts_ns;

    __u32 cpu;

    __u32 ev;

    __s32 pid;
    __s32 tid;
    __s32 tgid;
    __s32 ppid_unused;

    __s32 prio;

    __s32 prev_pid;
    __s32 prev_state;

    __s32 next_pid;

    __s32 success;

    char comm[TASK_COMM_LEN];
    char next_comm[TASK_COMM_LEN];
};


/*
 * --------------------------------------------------------------------------
 * ABI guard
 * --------------------------------------------------------------------------
 *
 * This MUST fail compilation if the wire record changes size.
 */
_Static_assert(
    sizeof(struct m1_event) == 84,
    "m1_event ABI mismatch: expected exactly 84 bytes"
);


/*
 * --------------------------------------------------------------------------
 * Ring buffer
 * --------------------------------------------------------------------------
 */
struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 8 * 1024 * 1024);
} m1_rb SEC(".maps");


/*
 * --------------------------------------------------------------------------
 * Drop counter
 * --------------------------------------------------------------------------
 *
 * Index 0:
 *   ring-buffer reservation failures
 */
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);

    __type(key, __u32);
    __type(value, __u64);
} m1_drops SEC(".maps");


static __always_inline void bump_drops(void)
{
    __u32 key = 0;

    __u64 *value = bpf_map_lookup_elem(
        &m1_drops,
        &key
    );

    if (value)
        __sync_fetch_and_add(value, 1);
}


/*
 * --------------------------------------------------------------------------
 * Allocate a clean event
 * --------------------------------------------------------------------------
 */
static __always_inline struct m1_event *reserve_zeroed(void)
{
    struct m1_event *event;

    event = bpf_ringbuf_reserve(
        &m1_rb,
        sizeof(*event),
        0
    );

    if (!event) {
        bump_drops();
        return 0;
    }

    /*
     * Ring-buffer memory is not assumed to be zeroed.
     *
     * Clear every byte before filling fields.
     */
    __builtin_memset(
        event,
        0,
        sizeof(*event)
    );

    /*
     * bpf_ktime_get_ns() uses the kernel monotonic clock.
     */
    event->ts_ns = bpf_ktime_get_ns();

    return event;
}


/*
 * --------------------------------------------------------------------------
 * sched_switch
 * --------------------------------------------------------------------------
 *
 * Kernel fields:
 *
 *   prev_comm
 *   prev_pid
 *   prev_prio
 *   prev_state
 *   next_comm
 *   next_pid
 *   next_prio
 *
 * M1 semantics:
 *
 *   pid/tid/comm = task being scheduled IN
 *   prev_pid     = task being scheduled OUT
 *   prev_state   = previous task state
 *   next_pid     = task being scheduled IN
 */
SEC("tracepoint/sched/sched_switch")
int on_switch(struct trace_event_raw_sched_switch *ctx)
{
    struct m1_event *event;

    event = reserve_zeroed();

    if (!event)
        return 0;

    event->cpu = bpf_get_smp_processor_id();
    event->ev = EV_SWITCH;

    /*
     * Primary task = task scheduled in.
     */
    event->pid = ctx->next_pid;
    event->tid = ctx->next_pid;

    event->prio = ctx->next_prio;

    event->prev_pid = ctx->prev_pid;
    event->prev_state = (__s32)ctx->prev_state;

    event->next_pid = ctx->next_pid;

    /*
     * IMPORTANT:
     *
     * Do not use __builtin_memcpy() directly with tracepoint context
     * pointers. The BPF verifier may reject the generated pointer
     * arithmetic as a modified ctx pointer.
     *
     * bpf_probe_read_kernel() is verifier-safe for this access pattern.
     */
    bpf_probe_read_kernel(
        event->comm,
        TASK_COMM_LEN,
        ctx->next_comm
    );

    bpf_probe_read_kernel(
        event->next_comm,
        TASK_COMM_LEN,
        ctx->next_comm
    );

    bpf_ringbuf_submit(
        event,
        0
    );

    return 0;
}


/*
 * --------------------------------------------------------------------------
 * sched_wakeup
 * --------------------------------------------------------------------------
 *
 * Actual target-kernel tracepoint fields:
 *
 *   comm[16]
 *   pid
 *   prio
 *   target_cpu
 *
 * There is NO:
 *
 *   ctx->p
 *   ctx->success
 */
SEC("tracepoint/sched/sched_wakeup")
int on_wakeup(struct trace_event_raw_sched_wakeup_template *ctx)
{
    struct m1_event *event;

    event = reserve_zeroed();

    if (!event)
        return 0;

    event->cpu = ctx->target_cpu;
    event->ev = EV_WAKEUP;

    event->pid = ctx->pid;
    event->tid = ctx->pid;

    event->prio = ctx->prio;

    /*
     * success intentionally remains zero.
     *
     * sched_wakeup does not expose a success field.
     *
     * IMPORTANT:
     *
     * Do NOT use:
     *
     *     __builtin_memcpy(event->comm, ctx->comm, TASK_COMM_LEN);
     *
     * because the compiler may generate a modified ctx pointer and the
     * verifier can reject it.
     *
     * Use the BPF kernel-read helper instead.
     */
    bpf_probe_read_kernel(
        event->comm,
        TASK_COMM_LEN,
        ctx->comm
    );

    bpf_ringbuf_submit(
        event,
        0
    );

    return 0;
}


/*
 * --------------------------------------------------------------------------
 * sched_wakeup_new
 * --------------------------------------------------------------------------
 *
 * Same tracepoint payload as sched_wakeup on the target kernel:
 *
 *   comm[16]
 *   pid
 *   prio
 *   target_cpu
 */
SEC("tracepoint/sched/sched_wakeup_new")
int on_wakeup_new(struct trace_event_raw_sched_wakeup_template *ctx)
{
    struct m1_event *event;

    event = reserve_zeroed();

    if (!event)
        return 0;

    event->cpu = ctx->target_cpu;
    event->ev = EV_WAKEUP_NEW;

    event->pid = ctx->pid;
    event->tid = ctx->pid;

    event->prio = ctx->prio;

    /*
     * success intentionally remains zero.
     *
     * Use bpf_probe_read_kernel() rather than __builtin_memcpy()
     * to avoid verifier rejection of modified ctx pointers.
     */
    bpf_probe_read_kernel(
        event->comm,
        TASK_COMM_LEN,
        ctx->comm
    );

    bpf_ringbuf_submit(
        event,
        0
    );

    return 0;
}


/*
 * --------------------------------------------------------------------------
 * sched_process_exec
 * --------------------------------------------------------------------------
 *
 * The kernel tracepoint format contains:
 *
 *   __data_loc char[] filename
 *   pid
 *   old_pid
 *
 * However, the generated vmlinux.h representation does not expose
 * "filename" as a normal BTF member usable by BPF_CORE_READ().
 *
 * Therefore M1 intentionally treats this event as an EXEC lifecycle event.
 *
 * The task name / executable identity is obtained from the synchronized
 * userspace /proc task observation layer.
 *
 * This avoids making the kernel event ABI dependent on the internal
 * __data_loc representation.
 *
 * pid:
 *   current task after exec
 *
 * old_pid:
 *   intentionally not represented in the current 84-byte ABI
 */
SEC("tracepoint/sched/sched_process_exec")
int on_exec(struct trace_event_raw_sched_process_exec *ctx)
{
    struct m1_event *event;

    event = reserve_zeroed();

    if (!event)
        return 0;

    event->cpu = bpf_get_smp_processor_id();
    event->ev = EV_EXEC;

    event->pid = ctx->pid;
    event->tid = ctx->pid;

    /*
     * We intentionally DO NOT attempt:
     *
     *     ctx->filename
     *
     * or:
     *
     *     BPF_CORE_READ(ctx, filename)
     *
     * because filename is a __data_loc tracepoint field and is not exposed
     * as a normal BTF member by the generated vmlinux.h.
     *
     * comm remains zero here.
     *
     * Userspace task snapshots provide the task/executable name.
     */

    bpf_ringbuf_submit(
        event,
        0
    );

    return 0;
}


/*
 * --------------------------------------------------------------------------
 * sched_process_exit
 * --------------------------------------------------------------------------
 *
 * Target kernel tracepoint format:
 *
 *   offset 0  : common trace-entry header (8 bytes used here)
 *   offset 8  : char comm[16]
 *   offset 24 : s32 pid
 *   offset 28 : s32 prio
 *
 * IMPORTANT:
 *
 * Do NOT use trace_event_raw_sched_process_template from vmlinux.h here.
 * That causes libbpf to create a CO-RE relocation for `comm`, and on the
 * target Kali kernel that relocation cannot be resolved:
 *
 *   <invalid CO-RE relocation> ... trace_event_raw_sched_process_template.comm
 *
 * This local fixed-layout structure intentionally contains only the bytes
 * needed from the verified tracepoint format. Its fields are accessed as
 * fixed offsets and therefore do not require a CO-RE relocation.
 */
struct m1_sched_process_exit_ctx {
    __u64 common_header;
    char comm[TASK_COMM_LEN];
    __s32 pid;
    __s32 prio;
};

SEC("tracepoint/sched/sched_process_exit")
int on_exit(struct m1_sched_process_exit_ctx *ctx)
{
    struct m1_event *event;

    event = reserve_zeroed();

    if (!event)
        return 0;

    event->cpu = bpf_get_smp_processor_id();
    event->ev = EV_EXIT;

    event->pid = ctx->pid;
    event->tid = ctx->pid;

    event->prio = ctx->prio;

    /*
     * Fixed-layout access; no vmlinux.h field relocation for comm.
     */
    bpf_probe_read_kernel(
        event->comm,
        TASK_COMM_LEN,
        ctx->comm
    );

    bpf_ringbuf_submit(
        event,
        0
    );

    return 0;
}


/*
 * --------------------------------------------------------------------------
 * GPL license
 * --------------------------------------------------------------------------
 */
char LICENSE[] SEC("license") = "GPL";
