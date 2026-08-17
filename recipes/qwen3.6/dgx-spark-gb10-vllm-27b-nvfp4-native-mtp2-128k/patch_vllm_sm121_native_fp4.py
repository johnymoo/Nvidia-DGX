from pathlib import Path

path = Path(
    "/usr/local/lib/python3.12/dist-packages/vllm/"
    "model_executor/kernels/linear/__init__.py"
)
text = path.read_text()
old = '''    PlatformEnum.CUDA: [
        # FlashInferB12xNvFp4LinearKernel excluded from auto-selection until
        # upstream CUTLASS SM121 MMA op guard is resolved; use
        # --linear-backend flashinfer_b12x to opt in explicitly.
        FlashInferCutlassNvFp4LinearKernel,
'''
new = '''    PlatformEnum.CUDA: [
        # GB10/SM121: prefer FlashInfer's native B12x block-scaled NVFP4 GEMM.
        # This is intentionally scoped to the NVFP4 registry so mixed FP8
        # layers continue to select their own compatible backend.
        FlashInferB12xNvFp4LinearKernel,
        FlashInferCutlassNvFp4LinearKernel,
'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"expected one NVFP4 registry marker, found {count}")
path.write_text(text.replace(old, new))
print(f"patched {path}")
