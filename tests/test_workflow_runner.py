import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("workflow_runner", ROOT / "worker/workflow_runner.py")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class WorkflowTests(unittest.TestCase):
    def test_contract_validates(self):
        diagram = RUNNER.load_workflow(ROOT)
        self.assertEqual(diagram["name"], "08-no-creds-siluet")
        self.assertEqual(diagram["items"]["11"]["type"], "action")

    def test_dry_paths_are_complete(self):
        for scenario, expected in (("live", "live"), ("empty", "empty"), ("checkpoint", "checkpoint"),
                                   ("vpn-failed", "dead"), ("route-failed", "blocked"),
                                   ("missing-scope", "blocked")):
            status, blocks = RUNNER.dry_result(scenario)
            self.assertEqual(status, expected)
            self.assertEqual(blocks[0], "3")

    def test_journal_hash_chain(self):
        output = ROOT / ".test-run.json"
        journal = RUNNER.Journal(output, 1, "HEAD", "abc", True)
        journal.add("3", {"simulated": True})
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["events"][1]["previous"], data["events"][0]["hash"])
        self.assertEqual(RUNNER.Journal.open(output).data["runId"], data["runId"])
        output.unlink()


if __name__ == "__main__":
    unittest.main()
