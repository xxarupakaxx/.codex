import copy
import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "validate-graph-contract.py"
)
SPEC = importlib.util.spec_from_file_location("validate_graph_contract", SCRIPT_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def valid_contract():
    return {
        "version": "1",
        "name": "research-write-review",
        "entrypoints": ["research"],
        "nodes": {
            "research": {
                "kind": "loop",
                "role": "worker",
                "authority": "read_only",
                "reads": ["brief"],
                "writes": ["research_notes"],
                "side_effect": "none",
            },
            "write": {
                "kind": "loop",
                "role": "worker",
                "authority": "artifact_writer",
                "reads": ["brief", "research_notes", "review_verdict"],
                "writes": ["artifact"],
                "side_effect": "none",
            },
            "review": {
                "kind": "loop",
                "role": "checker",
                "authority": "read_only",
                "reads": ["artifact"],
                "writes": ["review_verdict"],
                "side_effect": "none",
            },
            "done": {
                "kind": "function",
                "role": "worker",
                "authority": "read_only",
                "reads": ["artifact", "review_verdict"],
                "writes": [],
                "side_effect": "none",
            },
        },
        "state": {
            "brief": {
                "scope": "planning",
                "writer": "lead",
                "provenance": "wayfinder",
            },
            "research_notes": {
                "scope": "run",
                "writer": "research",
                "provenance": "node-output",
            },
            "artifact": {
                "scope": "artifact",
                "writer": "write",
                "provenance": "workspace",
            },
            "review_verdict": {
                "scope": "run",
                "writer": "review",
                "provenance": "fresh-check",
            },
        },
        "edges": [
            {"from": "research", "to": "write", "route": "static"},
            {"from": "write", "to": "review", "route": "static"},
            {
                "from": "review",
                "to": "write",
                "route": "deterministic",
                "condition": "approved == false",
                "loop": True,
                "max_iterations": 2,
                "stop_condition": "approved == true or max_iterations reached",
            },
            {
                "from": "review",
                "to": "done",
                "route": "deterministic",
                "condition": "approved == true",
            },
        ],
    }


class ValidateGraphContractTests(unittest.TestCase):
    def test_正常な契約を受理すべき(self):
        self.assertEqual([], VALIDATOR.validate_contract(valid_contract()))

    def test_到達不能なnodeを拒否すべき(self):
        contract = valid_contract()
        contract["nodes"]["orphan"] = copy.deepcopy(contract["nodes"]["done"])

        errors = VALIDATOR.validate_contract(contract)

        self.assertTrue(any("unreachable node: orphan" in error for error in errors))

    def test_stateのwriterとnodeの書き込みが一致すべき(self):
        contract = valid_contract()
        contract["state"]["artifact"]["writer"] = "research"

        errors = VALIDATOR.validate_contract(contract)

        self.assertTrue(
            any("state writer mismatch: write -> artifact" in error for error in errors)
        )

    def test_external_side_effectには安全策が必要であるべき(self):
        contract = valid_contract()
        contract["nodes"]["write"]["side_effect"] = "external"

        errors = VALIDATOR.validate_contract(contract)

        self.assertTrue(
            any(
                "external side effect requires safeguards: write" in error
                for error in errors
            )
        )

    def test_loopには停止条件と上限が必要であるべき(self):
        contract = valid_contract()
        loop_edge = contract["edges"][2]
        del loop_edge["stop_condition"]
        del loop_edge["max_iterations"]

        errors = VALIDATOR.validate_contract(contract)

        self.assertTrue(
            any("loop edge requires brake: review -> write" in error for error in errors)
        )

    def test_cycleには明示したloop_edgeが必要であるべき(self):
        contract = valid_contract()
        loop_edge = contract["edges"][2]
        del loop_edge["loop"]
        del loop_edge["stop_condition"]
        del loop_edge["max_iterations"]

        errors = VALIDATOR.validate_contract(contract)

        self.assertIn("cycle requires an explicit loop edge", errors)

    def test_checkerはartifactを書き換えられないべき(self):
        contract = valid_contract()
        contract["nodes"]["review"]["writes"] = ["artifact", "review_verdict"]

        errors = VALIDATOR.validate_contract(contract)

        self.assertTrue(
            any("checker cannot write artifact state: review" in error for error in errors)
        )

    def test_staticとdecision_routingを同じnodeで混在させないべき(self):
        contract = valid_contract()
        contract["edges"][3]["route"] = "static"

        errors = VALIDATOR.validate_contract(contract)

        self.assertTrue(
            any("mixed routing ownership: review" in error for error in errors)
        )

    def test_artifact_writer権限なしではartifactを書けないべき(self):
        contract = valid_contract()
        contract["nodes"]["write"]["authority"] = "read_only"

        errors = VALIDATOR.validate_contract(contract)

        self.assertIn("artifact write requires authority: write", errors)

    def test_artifact_writerはgraph全体で一人にすべき(self):
        contract = valid_contract()
        contract["nodes"]["research"]["authority"] = "artifact_writer"

        errors = VALIDATOR.validate_contract(contract)

        self.assertIn("graph must have at most one artifact writer", errors)

    def test_存在しないstate参照を拒否すべき(self):
        contract = valid_contract()
        contract["nodes"]["research"]["reads"].append("missing")

        errors = VALIDATOR.validate_contract(contract)

        self.assertTrue(
            any("unknown state reference: research -> missing" in error for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
