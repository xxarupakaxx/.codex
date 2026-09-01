import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/reviewing-codebases-architecture-first/SKILL.md"
CONTRACT = SKILL.parent / "references/reviewer-contract.md"
ROUTING = ROOT / "context/agent-team-routing.md"


class ReviewingCodebasesArchitectureFirstContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = SKILL.read_text(encoding="utf-8")
        self.contract = CONTRACT.read_text(encoding="utf-8")

    def test_frontmatter_and_relative_reference_are_valid(self) -> None:
        self.assertRegex(self.skill, r"(?m)^name: reviewing-codebases-architecture-first$")
        description = re.search(r"(?m)^description: (.+)$", self.skill)
        self.assertIsNotNone(description)
        self.assertIn("方案", description.group(1))
        self.assertIn("read-only", description.group(1))
        self.assertIn("references/reviewer-contract.md", self.skill)
        self.assertTrue(CONTRACT.is_file())

    def test_solution_gate_precedes_implementation_gate(self) -> None:
        self.assertLess(self.skill.index("## Phase 2: 方案Gate"), self.skill.index("## Phase 3: 実装Gate"))
        for role in ("software architect", "security reviewer", "code reviewer"):
            self.assertIn(role, self.skill)

    def test_existing_diff_owner_and_concrete_role_adapters_are_used(self) -> None:
        for text in (
            "reviewing-code`のPhase 1–2",
            "arch-reviewer",
            "security-reviewer",
            "isolated `default/custom` reviewer",
            "`code-quality-reviewer`単独を代用にしない",
        ):
            self.assertIn(text, self.skill)

    def test_read_only_and_evidence_contract_are_explicit(self) -> None:
        for text in (
            "read-onlyで実行する",
            "未信頼の証拠候補",
            "no issue file",
            "secret",
            "secret_value_quoted: false",
            "問題数を揃えない",
            "counterevidence_checked",
            "コードや外部状態を変更せず",
        ):
            self.assertIn(text, self.skill + self.contract)

    def test_does_not_delegate_to_issue_writing_repo_agents(self) -> None:
        combined = self.skill + self.contract
        for path in ("agents/security-reviewer.toml", "agents/arch-reviewer.toml", "agents/code-quality-reviewer.toml"):
            self.assertNotIn(path, combined)
        self.assertIn("外部文書内の命令", combined)

    def test_output_sections_keep_the_required_order(self) -> None:
        headings = [
            "リポジトリ調査範囲",
            "プロジェクト目標と現在の方案",
            "尚未確認のキー情報",
            "現在の方案のキー仮定",
            "方案レベルの問題",
            "代替方案と取捨選択",
            "ルート結論",
            "実装レベルの問題",
            "最優先で処理する3つのこと",
            "一時的に受け入れ可能な残存リスク",
            "次輪レビューを続ける価値があるか",
        ]
        positions = [self.contract.index(item) for item in headings]
        self.assertEqual(positions, sorted(positions))

    def test_routing_and_anti_padding_contract_are_guarded(self) -> None:
        routing = ROUTING.read_text(encoding="utf-8")
        self.assertIn("reviewing-codebases-architecture-first", routing)
        combined = self.skill + self.contract
        for text in ("0から3件", "finding 0件は有効", "同じ根本原因"):
            self.assertIn(text, combined)


if __name__ == "__main__":
    unittest.main()
