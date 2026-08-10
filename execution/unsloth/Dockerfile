FROM nvidia/cuda@sha256:450d11555d20ac8ebbbc13ebf17589c2bd42869171a90179ce7098b4a5e64c6a

ARG DEBIAN_FRONTEND=noninteractive
ARG LLAMA_REPOSITORY=https://github.com/hmirin/llama.cpp.git
ARG LLAMA_BRANCH=fix/rpc-multi-server-buffer-ownership
ARG LLAMA_COMMIT=f0c483c4df52f82cc5795433c9e9332fb3e8aa21

LABEL org.opencontainers.image.source="https://github.com/ggml-org/llama.cpp/pull/26500" \
      org.opencontainers.image.revision="f0c483c4df52f82cc5795433c9e9332fb3e8aa21" \
      io.shili.gb10-ds4.runtime="unsloth-llama-rpc-ab" \
      io.shili.gb10-ds4.model-snapshot="fbbb5b93fb787c21338159b0af3318bb3f4d9768"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      cmake \
      curl \
      git \
      libcurl4-openssl-dev \
      libibverbs-dev \
      pkg-config \
      rdma-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --filter=blob:none --single-branch --branch "$LLAMA_BRANCH" \
      --depth 64 "$LLAMA_REPOSITORY" llama.cpp \
    && cd llama.cpp \
    && git checkout --detach "$LLAMA_COMMIT" \
    && test "$(git rev-parse HEAD)" = "$LLAMA_COMMIT"

WORKDIR /opt/llama.cpp
RUN cmake -S . -B build \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_SHARED_LIBS=OFF \
      -DGGML_CUDA=ON \
      -DGGML_CUDA_GRAPHS=ON \
      -DGGML_NATIVE=OFF \
      -DGGML_RPC=ON \
      -DLLAMA_CURL=ON \
    && cmake --build build --parallel "$(nproc)" \
      --target llama-server llama-bench ggml-rpc-server

RUN install -m 0755 build/bin/llama-server /usr/local/bin/llama-server \
    && install -m 0755 build/bin/llama-bench /usr/local/bin/llama-bench \
    && install -m 0755 build/bin/ggml-rpc-server /usr/local/bin/ggml-rpc-server

WORKDIR /models
