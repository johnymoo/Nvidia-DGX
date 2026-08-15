FROM nvcr.io/nvidia/pytorch:26.07-py3@sha256:7531d90bcbe0e43e1f7363029c7e145ce90eebeb494a7b4695fdba0329d7c3c3

ARG VLLM_VERSION=0.25.0
ARG UV_VERSION=0.8.13
ARG FLASHINFER_VERSION=0.6.13
ARG CUTLASS_DSL_VERSION=4.5.2

LABEL org.opencontainers.image.title="GB10 Qwen3.8 NVFP4 vLLM runtime" \
      org.opencontainers.image.version="0.25.0" \
      io.shili.model-platform.model="unsloth/Qwen3.8-27B-NVFP4" \
      io.shili.model-platform.multimodal="text,image,video"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && uv pip install --system --torch-backend=auto \
      "vllm==${VLLM_VERSION}" \
      "flashinfer-python==${FLASHINFER_VERSION}" \
      "nvidia-cutlass-dsl==${CUTLASS_DSL_VERSION}"

RUN vllm --version \
    && python -c 'import flashinfer; print(flashinfer.__version__)' \
    && python -m pip freeze | LC_ALL=C sort > /usr/local/share/qwen38-runtime-requirements.txt

WORKDIR /models
