from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.validate import binary_findings, generated_findings, link_findings, privacy_findings, static_findings


class ValidatorTests(unittest.TestCase):
    def test_privacy_scan_reports_private_identity_and_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.md"
            credential_fixture = "api_" + "key='" + "fixture-credential-value'\n"
            path.write_text(
                "host=192.168.10.8\npath=/home/alice/models/file\n"
                + credential_fixture
            )
            messages = [finding.message for finding in privacy_findings(root, [path])]
            self.assertEqual(messages, ["private IPv4 address", "user home path", "literal credential"])

    def test_privacy_scan_allows_documentation_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.md"
            path.write_text("/home/YOUR_USERNAME/project\napi_key='dummy'\nhttp://127.0.0.1:8000\n")
            self.assertEqual(privacy_findings(root, [path]), [])

    def test_privacy_scan_reads_decodable_unknown_suffix_and_host_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "capture.data"
            path.write_text("ssh gb10-2\n")
            self.assertEqual([item.message for item in privacy_findings(root, [path])], ["private host alias"])

    def test_link_scan_handles_local_targets_and_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.md").write_text("# Target\n")
            source = root / "README.md"
            source.write_text(
                "[ok](target.md#target) [bad](missing.md) ![bad image](missing.png) "
                "[web](https://example.test)\n"
            )
            findings = link_findings(root, [source])
            self.assertEqual(len(findings), 2)
            self.assertIn("missing.md", findings[0].message)

    def test_link_scan_handles_html_and_repository_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "index.html"
            source.write_text('<a href="../outside.txt">bad</a><img src="missing.png">\n')
            findings = link_findings(root, [source])
            self.assertEqual(len(findings), 2)
            self.assertIn("escapes repository", findings[0].message)

    def test_binary_scan_denies_unreviewed_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "catalog").mkdir()
            (root / "catalog/publication-binaries.json").write_text(
                '{"schema_version":1,"exact":[],"prefixes":[]}\n'
            )
            binary = root / "artifact.bin"
            binary.write_bytes(b"\x00private")
            findings = binary_findings(root, [binary])
            self.assertEqual([item.message for item in findings], ["tracked binary is not publication-allowlisted"])

    def test_binary_scan_checks_allowlisted_pdf_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "catalog").mkdir()
            pdf = root / "report.pdf"
            pdf.write_bytes(b"%PDF-1.4\x00 host=192.168.20.4")
            digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
            (root / "catalog/publication-binaries.json").write_text(
                json.dumps({"schema_version": 1, "exact": [{"path": "report.pdf", "sha256": digest, "reason": "fixture"}], "prefixes": []})
            )
            messages = [item.message for item in binary_findings(root, [pdf])]
            self.assertIn("PDF private IPv4 address", messages)

    def test_static_scan_reports_invalid_json_and_python(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            (root / "tools" / "bad.json").write_text("{")
            (root / "tools" / "bad.py").write_text("if:\n")
            findings = static_findings(root)
            self.assertEqual({finding.path for finding in findings}, {"tools/bad.json", "tools/bad.py"})

    def test_static_scan_reports_invalid_shell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            (root / "tools" / "bad.sh").write_text("if true; then\n")
            findings = static_findings(root)
            self.assertEqual([finding.path for finding in findings], ["tools/bad.sh"])

    def test_generated_scan_detects_stale_catalog_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "catalog").mkdir()
            (root / "catalog" / "benchmark-policy.json").write_text(
                json.dumps(
                    {
                        "policy_id": "test",
                        "active_suites": {},
                        "required_identity": [],
                        "required_status": {},
                        "ranking": [],
                        "excluded_modalities": [],
                    }
                )
            )
            (root / "catalog" / "recipes.json").write_text("{}\n")
            (root / "catalog" / "latest-benchmarks.json").write_text("{}\n")
            findings = generated_findings(root)
            self.assertEqual(
                {finding.path for finding in findings},
                {"catalog/recipes.json", "catalog/latest-benchmarks.json"},
            )


if __name__ == "__main__":
    unittest.main()
