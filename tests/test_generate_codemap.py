from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate-codemap.py"
SPEC = importlib.util.spec_from_file_location("generate_codemap", SCRIPT)
assert SPEC and SPEC.loader
codemap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codemap)


class CodemapGeneratorContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "entry.py").write_text(
            "from .worker import run\n\nrun()\n", encoding="utf-8"
        )
        (self.root / "src" / "worker.py").write_text(
            "def run():\n    return 1\n", encoding="utf-8"
        )
        (self.root / "tests" / "test_worker.py").write_text(
            "def test_run():\n    assert True\n", encoding="utf-8"
        )
        self.source = self.root / "codemap.source.json"
        self.write_source()

        self.template = self.root / "roadmap_viewer.html"
        self.template.write_text(
            '<script id="embedded-snapshot" type="application/json">'
            f"{codemap.PLACEHOLDER}"
            "</script>",
            encoding="utf-8",
        )
        self.previous_template = codemap.TEMPLATE
        codemap.TEMPLATE = self.template

    def tearDown(self) -> None:
        codemap.TEMPLATE = self.previous_template
        self.temp_dir.cleanup()

    def write_source(self, **overrides: object) -> None:
        source = {
            "schemaVersion": 1,
            "title": "Sample code map",
            "description": "Evidence-backed topology",
            "scope": {
                "include": ["src/*.py", "tests/*.py"],
                "exclude": [],
            },
            "lanes": [
                {"id": "entrypoints", "title": "Entrypoints", "order": 0},
                {"id": "runtime", "title": "Runtime", "order": 1},
                {"id": "tests", "title": "Tests", "order": 2},
            ],
            "nodes": [
                {
                    "id": "entry",
                    "title": "Entry",
                    "kind": "entrypoint",
                    "lane": "entrypoints",
                    "path": "src/entry.py",
                },
                {
                    "id": "worker",
                    "title": "Worker",
                    "kind": "module",
                    "lane": "runtime",
                    "path": "src/worker.py",
                },
                {
                    "id": "test-worker",
                    "title": "Worker tests",
                    "kind": "test",
                    "lane": "tests",
                    "path": "tests/test_worker.py",
                },
            ],
            "edges": [
                {
                    "id": "entry-calls-worker",
                    "from": "entry",
                    "to": "worker",
                    "relation": "calls",
                    "status": "verified",
                    "evidence": [
                        {
                            "path": "src/entry.py",
                            "line": 1,
                            "contains": "from .worker import run",
                            "note": "imports run",
                        }
                    ],
                },
                {
                    "id": "tests-guard-worker",
                    "from": "test-worker",
                    "to": "worker",
                    "relation": "guards",
                    "status": "unknown",
                    "reason": "The fixture test does not import the worker yet.",
                    "evidence": [],
                },
            ],
        }
        source.update(overrides)
        self.source.write_text(
            json.dumps(source, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def refresh(self) -> dict[str, object]:
        return codemap.refresh(self.root, self.source)

    def test_refresh_writes_coherent_triad_and_lock_last(self) -> None:
        writes: list[str] = []
        original = codemap.atomic_write

        def record(path: Path, content: str) -> None:
            writes.append(path.name)
            original(path, content)

        with mock.patch.object(codemap, "atomic_write", side_effect=record):
            lock = self.refresh()

        self.assertEqual(writes, ["codemap.json", "codemap.html", "codemap.lock"])
        self.assertEqual(codemap.check(self.root)["status"], "fresh")
        self.assertEqual(lock, json.loads((self.root / "codemap.lock").read_text()))

        map_bytes = (self.root / "codemap.json").read_bytes()
        html_bytes = (self.root / "codemap.html").read_bytes()
        self.assertEqual(lock["mapFingerprint"], codemap.sha256_bytes(map_bytes))
        self.assertEqual(lock["htmlFingerprint"], codemap.sha256_bytes(html_bytes))
        self.assertEqual(
            codemap.extract_embedded_snapshot((self.root / "codemap.html").read_text()),
            json.loads(map_bytes),
        )

    def test_partial_refresh_never_passes_check(self) -> None:
        for fail_on in ("codemap.html", "codemap.lock"):
            with self.subTest(fail_on=fail_on):
                self.refresh()
                source = json.loads(self.source.read_text())
                source["description"] = f"new payload before {fail_on}"
                self.source.write_text(json.dumps(source))
                original = codemap.atomic_write

                def fail(path: Path, content: str) -> None:
                    if path.name == fail_on:
                        raise RuntimeError("injected write failure")
                    original(path, content)

                with mock.patch.object(codemap, "atomic_write", side_effect=fail):
                    with self.assertRaisesRegex(RuntimeError, "injected"):
                        self.refresh()
                with self.assertRaises(codemap.CodemapStateError):
                    codemap.check(self.root)

                self.write_source()

    def test_verified_edge_requires_existing_line_evidence(self) -> None:
        source = json.loads(self.source.read_text())
        source["edges"][0]["evidence"] = []
        self.source.write_text(json.dumps(source))

        with self.assertRaisesRegex(codemap.CodemapValidationError, "verified.*evidence"):
            self.refresh()

        source["edges"][0]["evidence"] = [{"path": "src/missing.py", "line": 1}]
        self.source.write_text(json.dumps(source))
        with self.assertRaisesRegex(codemap.CodemapValidationError, "does not exist"):
            self.refresh()

        source["edges"][0]["evidence"] = [{"path": "src/entry.py", "line": 99}]
        self.source.write_text(json.dumps(source))
        with self.assertRaisesRegex(codemap.CodemapValidationError, "outside"):
            self.refresh()

        self.write_source()
        source = json.loads(self.source.read_text())
        source["edges"][0]["evidence"][0].pop("contains")
        self.source.write_text(json.dumps(source))
        with self.assertRaisesRegex(codemap.CodemapValidationError, "contains"):
            self.refresh()

        source["edges"][0]["evidence"][0]["contains"] = "not on this line"
        self.source.write_text(json.dumps(source))
        with self.assertRaisesRegex(codemap.CodemapValidationError, "not found"):
            self.refresh()

    def test_unknown_edge_requires_reason(self) -> None:
        source = json.loads(self.source.read_text())
        source["edges"][1].pop("reason")
        self.source.write_text(json.dumps(source))

        with self.assertRaisesRegex(codemap.CodemapValidationError, "unknown.*reason"):
            self.refresh()

    def test_check_detects_changed_added_and_deleted_sources(self) -> None:
        self.refresh()

        worker = self.root / "src" / "worker.py"
        worker.write_text("def run():\n    return 2\n")
        with self.assertRaisesRegex(codemap.CodemapStateError, "source fingerprint"):
            codemap.check(self.root)

        self.refresh()
        (self.root / "src" / "added.py").write_text("VALUE = 1\n")
        with self.assertRaisesRegex(codemap.CodemapStateError, "source fingerprint"):
            codemap.check(self.root)

        self.refresh()
        worker.unlink()
        with self.assertRaisesRegex(codemap.CodemapStateError, "source fingerprint"):
            codemap.check(self.root)

    def test_outputs_are_never_part_of_source_manifest(self) -> None:
        self.write_source(scope={"include": ["**/*"], "exclude": []})
        self.refresh()
        self.refresh()

        lock = json.loads((self.root / "codemap.lock").read_text())
        paths = {item["path"] for item in lock["sourceManifest"]}
        self.assertNotIn("codemap.json", paths)
        self.assertNotIn("codemap.html", paths)
        self.assertNotIn("codemap.lock", paths)
        self.assertFalse(any(Path(path).name.startswith(".codemap.") for path in paths))
        self.assertEqual(codemap.check(self.root)["status"], "fresh")

    def test_source_manifest_does_not_follow_symlinked_directories(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir)
            (outside / "secret.py").write_text("TOKEN = 'outside'\n", encoding="utf-8")
            try:
                (self.root / "linked").symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks are unavailable: {error}")
            self.write_source(scope={"include": ["linked/*.py"], "exclude": []})

            with self.assertRaisesRegex(
                codemap.CodemapValidationError, "scope pattern has no files"
            ):
                self.refresh()

    def test_check_rejects_tampered_map_html_or_missing_lock(self) -> None:
        self.refresh()
        map_path = self.root / "codemap.json"
        map_path.write_text(map_path.read_text() + " ")
        with self.assertRaisesRegex(codemap.CodemapStateError, "map fingerprint"):
            codemap.check(self.root)

        self.refresh()
        html_path = self.root / "codemap.html"
        html_path.write_text(html_path.read_text() + "<!-- changed -->")
        with self.assertRaisesRegex(codemap.CodemapStateError, "html fingerprint"):
            codemap.check(self.root)

        self.refresh()
        (self.root / "codemap.lock").unlink()
        with self.assertRaisesRegex(codemap.CodemapStateError, "missing codemap.lock"):
            codemap.check(self.root)

    def test_check_rejects_coherently_rewritten_generated_metadata(self) -> None:
        for field in ("kind", "version", "sourceFingerprint", "counts"):
            with self.subTest(field=field):
                self.refresh()
                snapshot = json.loads((self.root / "codemap.json").read_text())
                snapshot.pop(field)
                map_content = codemap.json_text(snapshot)
                html_content = codemap.render_html(snapshot)
                lock = json.loads((self.root / "codemap.lock").read_text())
                lock["mapFingerprint"] = codemap.sha256_bytes(map_content.encode())
                lock["htmlFingerprint"] = codemap.sha256_bytes(html_content.encode())
                (self.root / "codemap.json").write_text(map_content)
                (self.root / "codemap.html").write_text(html_content)
                (self.root / "codemap.lock").write_text(codemap.json_text(lock))

                with self.assertRaisesRegex(
                    codemap.CodemapStateError, "invalid codemap.json"
                ):
                    codemap.check(self.root)

    def test_check_rejects_changed_source_spec_or_template(self) -> None:
        self.refresh()
        source = json.loads(self.source.read_text())
        source["description"] = "Changed draft"
        self.source.write_text(json.dumps(source))
        with self.assertRaisesRegex(codemap.CodemapStateError, "source spec"):
            codemap.check(self.root)

        self.write_source()
        self.refresh()
        self.template.write_text(self.template.read_text() + "\n")
        with self.assertRaisesRegex(codemap.CodemapStateError, "template"):
            codemap.check(self.root)

    def test_template_fingerprint_ignores_platform_line_endings(self) -> None:
        content = (
            '<script id="embedded-snapshot" type="application/json">\n'
            f"{codemap.PLACEHOLDER}\n"
            "</script>\n"
        )
        self.template.write_text(content)
        self.refresh()
        self.template.write_bytes(content.replace("\n", "\r\n").encode())

        self.assertEqual(codemap.check(self.root)["status"], "fresh")

    def test_schema_rejects_duplicate_ids_unknown_lanes_and_escaping_paths(self) -> None:
        source = json.loads(self.source.read_text())
        source["nodes"][1]["id"] = "entry"
        self.source.write_text(json.dumps(source))
        with self.assertRaisesRegex(codemap.CodemapValidationError, "duplicate node"):
            self.refresh()

        self.write_source()
        source = json.loads(self.source.read_text())
        source["nodes"][0]["lane"] = "missing"
        self.source.write_text(json.dumps(source))
        with self.assertRaisesRegex(codemap.CodemapValidationError, "unknown lane"):
            self.refresh()

        self.write_source()
        source = json.loads(self.source.read_text())
        source["edges"][0]["evidence"][0]["path"] = "../outside.py"
        self.source.write_text(json.dumps(source))
        with self.assertRaisesRegex(codemap.CodemapValidationError, "repo-relative"):
            self.refresh()


if __name__ == "__main__":
    unittest.main()
