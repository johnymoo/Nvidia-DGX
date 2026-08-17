#!/usr/bin/env python3

import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).parent / "sanitize-results.py"
    spec = importlib.util.spec_from_file_location("sanitize_results", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_incomplete_samples(module, case, message):
    try:
        module.extrema(case)
    except RuntimeError as error:
        assert str(error) == message
    else:
        raise AssertionError("incomplete resource samples were accepted")


def main():
    module = load_module()
    expect_incomplete_samples(
        module,
        {"id": "no-samples", "resources": []},
        "resource samples are incomplete for case no-samples: "
        "no available_memory_kib values",
    )
    expect_incomplete_samples(
        module,
        {"id": "no-gpu", "resources": [{
            "available_memory_kib": 1,
            "comfyui_rss_kib": 1,
            "gpu_temperature_celsius": 1,
            "gpu_power_draw_watts": 1,
        }]},
        "resource samples are incomplete for case no-gpu: "
        "no gpu_utilization_percent values",
    )


if __name__ == "__main__":
    main()
