# Two-node GB10 cluster topology

## Logical topology

```text
                         Management / API plane
  Claude Code or client -------------------------------------------+
                                                                   |
                                                    OpenAI/Anthropic adapter
                                                                   |
                                                    +--------------v-------+
                                                    | GB10 head, rank 0    |
                                                    | API + scheduler      |
                                                    | one model shard      |
                                                    +----------+-----------+
                                                               |
                       Dedicated high-speed fabric              |
                       NCCL NET/IB over RoCE/RDMA                |
                       tensor-parallel collectives              |
                                                               |
                                                    +----------v-----------+
                                                    | GB10 worker, rank 1  |
                                                    | --headless           |
                                                    | one model shard      |
                                                    +----------------------+
```

The model is one distributed process with two ranks, not two independent API
replicas. `--tensor-parallel-size 2`, `--nnodes 2`, and one GPU per GB10 split
each inference step across both machines. Losing either rank invalidates the
service. Only rank 0 exposes the API; rank 1 uses `--headless`.

## Node contract

| Setting | Head | Worker |
|---|---|---|
| `NODE_RANK` | `0` | `1` |
| `HEADLESS` | empty | `1` |
| `VLLM_HOST_IP` | head fabric address | worker fabric address |
| `MASTER_ADDR` | head fabric address | same head fabric address |
| `MASTER_PORT` | same free rendezvous port | same port |
| model/image/config | identical | identical |
| API ownership | binds configured API port | none |

Use a dedicated fabric subnet with no default route. The management network is
for SSH, monitoring and API access; tensor traffic belongs on the RDMA fabric.
The accepted shape used a ConnectX-class RoCE link, MTU 9000, active RDMA on
both ends, and matching GID selection. Exact interface names and addresses are
site-specific and belong in `.env`, not Git.

## Container and memory path

Both ranks use host networking and IPC, all local GPU devices, unlimited
memlock, a 64 GiB shared-memory allocation, and `/dev/infiniband`. The model
checkpoint is mounted read-only at the same container path. Hugging Face and
vLLM caches are local to each node, so both nodes must have complete, identical
weights before startup.

```text
checkpoint shard -> local unified CPU/GPU memory -> local GB10 GPU execution
                                              |
                                  NCCL tensor collective
                                              |
                                  peer GB10 GPU execution
```

Tensor parallelism does not turn the pair into one cache filesystem. Avoid
loading a second large model on either node while DeepSeek is active unless a
separate capacity test proves coexistence.

## Startup and shutdown order

Start the worker first so rank 1 waits for rendezvous, then start the head.
Readiness is owned by the head API only after both ranks complete model load,
KV profiling, distributed initialization and graph/autotune work.

Stop the head first to remove API traffic, then stop the worker. Treat a
one-rank container, a socket fallback, an identity mismatch, or missing rank
logs as a failed cluster rather than a degraded service.

## Failure boundaries

Hard failures include either rank exiting, CUDA or NCCL fatal errors, Linux OOM
kills, GPU Xid events, RDMA link loss, or model identity mismatch. A transient
driver allocation warning during warmup is not sufficient evidence of failure
if initialization subsequently completes, but it must remain in the run log.

The API health endpoint alone is not full acceptance. Preserve evidence that
both ranks joined and that NCCL selected the RDMA path instead of sockets.
