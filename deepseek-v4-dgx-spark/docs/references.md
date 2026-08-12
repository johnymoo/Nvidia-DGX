# Models and upstream references

## Default model

The deployment in this directory targets the official checkpoint:

- [deepseek-ai/DeepSeek-V4-Flash-0731](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- Upstream deployment provenance records the tested model revision as
  `9e165c30`. Resolve and record the current full commit before downloading; do
  not silently follow a moving repository head.

Example with the Hugging Face CLI:

```bash
MODEL_REPO=deepseek-ai/DeepSeek-V4-Flash-0731
MODEL_REVISION=9e165c30
MODEL_DIR=/path/to/models/DeepSeek-V4-Flash-0731

huggingface-cli download "$MODEL_REPO" \
  --revision "$MODEL_REVISION" \
  --local-dir "$MODEL_DIR"
```

Use `hf download` instead on newer CLI releases. After download, create a
sorted SHA-256 manifest for the entire directory and compare it on both nodes.
The repository does not redistribute weights; follow the model card license
and access terms.

## Runtime and Patch4

- [Official 0731 two-DGX Spark recipe](https://github.com/tonyd2wild/DeepSeek-v4-Flash-0731-DSpark-1M-NVFP4-KV-2x-DGX-Spark)
- [Pinned tested recipe commit `f277b3d`](https://github.com/tonyd2wild/DeepSeek-v4-Flash-0731-DSpark-1M-NVFP4-KV-2x-DGX-Spark/commit/f277b3dfa718a5962bed64e69e7e640a5384ec2f)
- [vLLM upstream](https://github.com/vllm-project/vllm)
- [FlashInfer](https://github.com/flashinfer-ai/flashinfer)
- [Keys DSpark concurrency patch history](https://github.com/drowzeys/Keys-Concurrency-Patch-for-DSpark-DeepSeek-V4-Flash)
- [Fraser Price DSpark vLLM work](https://github.com/fraserprice/dspark-vllm)
- [MiaAI-Lab two-DGX Spark recipe](https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark)

Patch4 fixes the DSpark draft loader's missing always-on shared expert tensors.
Pin the complete runtime repository/image revision; installing a current stock
vLLM package does not reproduce this runtime contract.

## Related model variants

These are references, not drop-in defaults for the Compose in this directory:

- [fraserprice/DeepSeek-V4-Flash-DSpark](https://huggingface.co/fraserprice/DeepSeek-V4-Flash-DSpark): preview DSpark checkpoint used by older performance work.
- [drowzeys/keys-DeepSeekV4-Flash-GA-0731-Dspark-Abliterated-32-32](https://huggingface.co/drowzeys/keys-DeepSeekV4-Flash-GA-0731-Dspark-Abliterated-32-32): gated abliterated variant with separate responsible-use terms.
- [unsloth/DeepSeek-V4-Flash-0731-GGUF](https://huggingface.co/unsloth/DeepSeek-V4-Flash-0731-GGUF): GGUF/llama.cpp route, previously evaluated at revision `fbbb5b93fb787c21338159b0af3318bb3f4d9768`; it is a different runtime and quantization path.
- [llama.cpp](https://github.com/ggml-org/llama.cpp): runtime used for GGUF alternatives, not for the vLLM Patch4 deployment.

Do not compare throughput from preview, GGUF, abliterated or different vLLM
revisions as though only the model name changed.

## Client and benchmark references

- [coding-agent-toolchain](https://github.com/johnymoo/coding-agent-toolchain): route shim defining `claude_ds` and `claude_local`; the original run recorded commit `c074ba8f6858f3646b0f6f27435b48c1678d33b8`.
- [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code/overview)
- [SWE-bench](https://github.com/SWE-bench/SWE-bench): reference for SWE-style task construction. The included corpus is project-owned and does not require the SWE-bench Docker harness.
- [Codex CLI](https://github.com/openai/codex): executes the frozen `gpt-5.6-sol/xhigh` blind judge contract used by the benchmark.

## Hardware and network references

- [NVIDIA DGX Spark documentation](https://docs.nvidia.com/dgx/dgx-spark/)
- [NVIDIA NCCL documentation](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/)
- [NVIDIA RDMA-aware networking documentation](https://docs.nvidia.com/networking/display/rdmaawareprogrammingv17)
- [Docker Compose file reference](https://docs.docker.com/reference/compose-file/)
- [vLLM parallelism and scaling guide](https://docs.vllm.ai/en/latest/serving/parallelism_scaling/)

External links describe upstream behavior. The accepted values for this project
are the pinned Compose render and local evidence, not an unversioned web page.
