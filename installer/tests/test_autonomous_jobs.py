"""Regression tests for finite, crash-safe unattended document jobs."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import autonomous_jobs as jobs


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "control").mkdir()
        (self.root / "control/config.json").write_text(json.dumps({
            "api_key": "test-only",
            "text_models": {"local-ai": {"model": "test-model"}}
        }))
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.folder = jobs.locations(self.root, "a" * 32)
        (self.folder / "outputs").mkdir(parents=True)
        self.items = []
        self.job = {"version": 1, "id": "a" * 32, "source": str(self.inputs),
                    "instruction": "Extract practical lessons with evidence",
                    "model": "local-ai", "items": self.items}
        self.state = {"status": "pending", "complete": {}, "attempts": {}}

    def file(self, name, content):
        path = self.inputs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.items.append({"path": name, "sha256": jobs.checksum(content.encode()),
                           "bytes": len(content.encode())})

    def save(self):
        jobs.atomic_json(self.folder / "job.json", self.job)
        jobs.atomic_json(self.folder / "state.json", self.state)

    def run(self, model=None):
        model = model or (lambda config, job, item, content: b"## Verified\n" + content.encode() + b"\n")
        config = {"api_key": "test-only", "text_models": {"local-ai": {}}}
        with patch.object(jobs, "allowed_mode", return_value=config), patch.object(jobs, "inference", side_effect=model):
            return jobs.run_job(self.root, self.job["id"])

    def test_ten_items_are_checkpointed_across_bounded_runs(self):
        for i in range(10):
            self.file(f"item-{i}.md", f"Content {i}")
        self.save()
        first = self.run()
        self.assertEqual(first["status"], "pending")
        self.assertEqual(len(first["complete"]), 8)
        second = self.run()
        self.assertEqual(second["status"], "complete")
        self.assertEqual(len(second["complete"]), 10)
        self.assertEqual(self.run()["status"], "complete")

    def test_prepared_result_recovers_without_second_model_call(self):
        self.file("one.md", "Initial")
        self.state["prepared"] = {"one.md": jobs.checksum(b"Recovered\n")}
        self.save()
        output = self.folder / "outputs" / jobs.output_name(0, self.items[0])
        jobs.publish(output, b"Recovered\n")
        with patch.object(jobs, "allowed_mode", side_effect=AssertionError("no model after recovery")):
            result = jobs.run_job(self.root, self.job["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["complete"]["one.md"], jobs.checksum(b"Recovered\n"))

    def test_unrecorded_existing_artifact_requires_manual_review(self):
        self.file("one.md", "Initial")
        self.save()
        output = self.folder / "outputs" / jobs.output_name(0, self.items[0])
        jobs.publish(output, b"Unknown\n")
        result = self.run()
        self.assertEqual(result["status"], "needs-review")
        self.assertEqual(result["complete"], {})

    def test_tampered_completed_artifact_is_not_silently_skipped(self):
        self.file("one.md", "Initial")
        self.assertEqual(self.run_after_save(), "complete")
        output = self.folder / "outputs" / jobs.output_name(0, self.items[0])
        output.write_text("Modified\n")
        result = self.run()
        self.assertEqual(result["status"], "needs-review")

    def run_after_save(self):
        self.save()
        return self.run()["status"]

    def test_changed_input_prevents_inference(self):
        self.file("one.md", "Original")
        self.save()
        (self.inputs / "one.md").write_text("Changed")
        result = self.run()
        self.assertEqual(result["status"], "needs-review")
        self.assertEqual(result["attempts"]["one.md"], 1)

    def test_model_error_retries_only_twice(self):
        self.file("one.md", "Original")
        self.save()
        def failure(*args):
            raise RuntimeError("inference unavailable")
        first = self.run(failure)
        second = self.run(failure)
        self.assertEqual(first["status"], "pending")
        self.assertEqual(second["status"], "needs-review")
        self.assertEqual(second["attempts"]["one.md"], 2)
        self.assertEqual(self.run()["status"], "needs-review")

    def test_stop_marker_prevents_work(self):
        self.file("one.md", "Original")
        self.save()
        (self.folder / "STOP").touch()
        result = self.run()
        self.assertEqual(result["complete"], {})

    def test_symlinks_and_hardlinks_are_rejected(self):
        self.file("one.txt", "Original")
        os.link(self.inputs / "one.txt", self.inputs / "two.txt")
        with self.assertRaises(ValueError):
            jobs.inventory(self.inputs)
        (self.inputs / "two.txt").unlink()
        (self.inputs / "link.txt").symlink_to(self.inputs / "one.txt")
        with self.assertRaises(ValueError):
            jobs.inventory(self.inputs)

    def test_unsupported_input_types_do_not_enter_inventory(self):
        self.file("one.md", "Evidence")
        (self.inputs / "binary.bin").write_bytes(b"\xff")
        inventory = jobs.inventory(self.inputs)
        self.assertEqual([record["path"] for record in inventory], ["one.md"])

    def test_full_inventory_exceeds_small_text_read_limit_without_failing_load(self):
        for index in range(120):
            self.file(f"item-{index:03d}.md", "Small")
        self.save()
        self.assertGreater((self.folder / "job.json").stat().st_size, 10_000)
        _, job, state = jobs.load(self.root, self.job["id"])
        self.assertEqual(len(job["items"]), 120)

    def test_output_publish_is_create_only(self):
        path = self.folder / "outputs" / "result.md"
        jobs.publish(path, b"First\n")
        with self.assertRaises(FileExistsError):
            jobs.publish(path, b"Second\n")
        self.assertEqual(path.read_bytes(), b"First\n")

    def test_gaming_and_scoped_automation_block_inference(self):
        self.file("one.md", "Evidence")
        self.save()
        with patch.object(jobs, "http", return_value={"mode": "gaming", "transitioning": False, "error": False}):
            result = jobs.run_job(self.root, self.job["id"])
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["complete"], {})
        config_path = self.root / "control/config.json"
        config = json.loads(config_path.read_text())
        config["desktop"] = {"enabled": True}
        config_path.write_text(json.dumps(config))
        with patch.object(jobs, "http", side_effect=AssertionError("must not infer")):
            self.assertEqual(jobs.run_job(self.root, self.job["id"])["status"], "pending")


if __name__ == "__main__":
    unittest.main()
