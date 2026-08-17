import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_thinking import inspect_stream, verify_compose, verify_streams


class VerifyThinkingTests(unittest.TestCase):
    def test_all_compose_commands_report_prompt_cache_tokens(self) -> None:
        flag = "--enable-prompt-tokens-details"
        for filename in ("docker-compose.yml", "docker-compose.thinking-on.yml"):
            with self.subTest(filename=filename):
                compose = (PROJECT_ROOT / filename).read_text(encoding="utf-8")
                self.assertEqual(compose.count(flag), 1)

    def test_compose_requires_thinking_on(self) -> None:
        payload = {
            "services": {
                "vllm-dspark": {
                    "environment": {"DSPARK_THINKING": "true"},
                    "command": [
                        "bash",
                        "-lc",
                        "vllm serve --default-chat-template-kwargs "
                        "'{\"thinking\":true}'",
                    ],
                }
            }
        }
        self.assertTrue(verify_compose(payload)["thinking"])

    def test_compose_rejects_thinking_off(self) -> None:
        payload = {
            "services": {
                "vllm-dspark": {
                    "environment": {"DSPARK_THINKING": "true"},
                    "command": ["--default-chat-template-kwargs '{\"thinking\":false}'"],
                }
            }
        }
        with self.assertRaises(ValueError):
            verify_compose(payload)

    def test_stream_counts_thinking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stream.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "content": [
                                        {"type": "thinking", "thinking": "check"}
                                    ]
                                },
                            }
                        ),
                        json.dumps(
                            {"type": "system", "subtype": "thinking_tokens"}
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "content": [{"type": "text", "text": "done"}]
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            result = inspect_stream(path)
            self.assertEqual(result["assistant_events"], 2)
            self.assertEqual(result["thinking_blocks"], 1)
            self.assertEqual(result["thinking_token_events"], 1)
            self.assertEqual(verify_streams([path])["stream_count"], 1)

    def test_stream_rejects_missing_thinking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stream.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "done"}]},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                verify_streams([path])


if __name__ == "__main__":
    unittest.main()
