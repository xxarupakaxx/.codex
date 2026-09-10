from __future__ import annotations
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from roadmap_plan_contract import parse_html_plan_contract
from plan_execution_contract import readiness, design_hash, execution_brief


def plan_html():
    fields = ''.join(f'<section data-field="{name}"><p>{name} actual user outcome</p></section>' for name in ('intent', 'assumptions', 'approach', 'success-scenarios'))
    task_fields = ''.join(f'<section data-field="{name}"><p>{name} explicit condition</p></section>' for name in ('purpose', 'targets', 'outputs', 'verification', 'decision-boundaries', 'stop-conditions', 'negative-paths'))
    return f'''<main data-plan-schema="2"><section data-field="execution-contract-version"><p>1</p></section><h1>Execution fixture</h1>{fields}
<section data-task-id="1"><h2>Implement</h2>{task_fields}
<section data-field="implementation"><ol><li><input type="checkbox" disabled>first reproduce defect</li><li>then implement</li></ol><pre><code>if mismatch:\n    stop()</code></pre></section>
<section data-field="acceptance"><ul><li data-acceptance-id="A1">user completes journey</li></ul></section></section></main>'''


def write_receipt(task, model):
    receipt = {'schemaVersion': 1, 'authorId': 'maker', 'planDesignSha256': design_hash(model),
               'requestSha256': hashlib.sha256((task/'00_request.md').read_bytes()).hexdigest(),
               'reviews': {stage: {'verdict': 'pass', 'reviewerId': 'checker', 'basis': 'user request compared to scenario',
                                    'counterexample': 'technically correct output can still miss the goal', 'evidence': 'fixture independent review output', 'openFindings': []}
                           for stage in ('intent', 'plan')}}
    for stage in ('intent', 'plan'):
        evidence = f'Fixture {stage} review: checked original request and counterexample.'
        (task/f'{stage}-review.md').write_text(evidence)
        receipt['reviews'][stage]['evidenceSha256'] = hashlib.sha256(evidence.encode()).hexdigest()
    receipt['reviews']['plan']['intentReviewSha256'] = hashlib.sha256(json.dumps(receipt['reviews']['intent'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    (task/'plan-review.json').write_text(json.dumps(receipt))
    return receipt


class ExecutionContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.task = Path(self.temp.name)/'task'
        self.task.mkdir()
        self.html = plan_html()
        self.model = parse_html_plan_contract(self.html)
        (self.task/'30_plan.html').write_text(self.html)
        (self.task/'00_request.md').write_text('Original user request: complete journey')
        (self.task/'05_log.md').write_text('roadmap_route: roadmap\n')
        self.receipt = write_receipt(self.task, self.model)

    def test_reviewed_plan_passes_and_execution_preserves_order(self):
        brief = execution_brief(self.task, self.model, '1')
        self.assertTrue(brief['gate']['canImplement'])
        self.assertEqual(brief['task']['implementation'], ['first reproduce defect', 'then implement'])
        self.assertIn('stop()', brief['task']['body'])
        self.assertIn('if mismatch:\\n    stop()', json.dumps(brief['task']['document']))

    def test_missing_contract_keeps_plan_parseable_but_cannot_execute(self):
        for name in ('intent', 'assumptions', 'approach', 'success-scenarios', 'decision-boundaries', 'stop-conditions', 'negative-paths'):
            model = parse_html_plan_contract(self.html.replace(f'data-field="{name}"', ''))
            with self.subTest(name=name):
                self.assertFalse(readiness(self.task, model)['canImplement'])

    def test_rejected_goal_blocks_even_with_plan_review_pass(self):
        self.receipt['reviews']['intent']['verdict'] = 'revise'
        (self.task/'plan-review.json').write_text(json.dumps(self.receipt))
        result = readiness(self.task, self.model)
        self.assertIn('review_not_pass:intent', result['blockers'])
        self.assertFalse(result['canImplement'])

    def test_request_or_plan_change_invalidates_previous_review(self):
        changed = parse_html_plan_contract(self.html.replace('user completes journey', 'API responds 200'))
        self.assertIn('stale_review:planDesignSha256', readiness(self.task, changed)['blockers'])
        (self.task/'00_request.md').write_text('A changed goal')
        self.assertIn('stale_review:requestSha256', readiness(self.task, self.model)['blockers'])

    def test_progress_only_does_not_invalidate_review(self):
        model = parse_html_plan_contract(self.html.replace('type="checkbox" disabled', 'type="checkbox" disabled checked'))
        self.assertEqual(design_hash(self.model), design_hash(model))
        self.assertTrue(readiness(self.task, model)['canImplement'])

    def test_ui_checked_state_is_design_not_progress(self):
        before = parse_html_plan_contract(self.html.replace('</main>', '<div><input type="checkbox" disabled></div></main>'))
        after = parse_html_plan_contract(self.html.replace('</main>', '<div><input type="checkbox" disabled checked></div></main>'))
        self.assertNotEqual(design_hash(before), design_hash(after))

    def test_author_cannot_self_review_and_findings_block(self):
        self.receipt['reviews']['intent'].update(reviewerId='maker', openFindings=['goal mismatch'])
        (self.task/'plan-review.json').write_text(json.dumps(self.receipt))
        errors = readiness(self.task, self.model)['blockers']
        self.assertIn('independent_reviewer_required:intent', errors)
        self.assertIn('unresolved_findings:intent', errors)

    def test_receipt_symlink_duplicate_and_oversized_fail_closed(self):
        path = self.task/'plan-review.json'
        for raw in ('{"schemaVersion":1,"schemaVersion":1}', 'x'*131073, 'null', '[]'):
            path.write_text(raw)
            self.assertFalse(readiness(self.task, self.model)['canImplement'])
        path.unlink()
        path.symlink_to(self.task/'00_request.md')
        self.assertFalse(readiness(self.task, self.model)['canImplement'])

    def test_long_instruction_tail_is_preserved(self):
        text = 'Do this. '*400 + 'STOP IF ORIGINAL INTENT DIFFERS'
        model = parse_html_plan_contract(self.html.replace('then implement', text))
        write_receipt(self.task, model)
        brief = execution_brief(self.task, model, '1')
        self.assertIn(text, brief['task']['implementation'])
        self.assertIn('STOP IF ORIGINAL INTENT DIFFERS', brief['task']['body'])

    def test_cli_legacy_inspection_succeeds_but_execution_fails(self):
        (self.task/'plan-review.json').unlink()
        cmd = [sys.executable, str(ROOT/'scripts/task-context.py'), 'brief', str(self.task)]
        inspect = subprocess.run(cmd, capture_output=True, text=True)
        execute = subprocess.run(cmd+['--execution'], capture_output=True, text=True)
        self.assertEqual(inspect.returncode, 0)
        self.assertFalse(json.loads(inspect.stdout)['executionReadiness']['canImplement'])
        self.assertEqual(execute.returncode, 2)
        self.assertIsNone(json.loads(execute.stdout)['selectedTask'])

    def test_cli_pass_returns_full_contract(self):
        result = subprocess.run([sys.executable, str(ROOT/'scripts/task-context.py'), 'brief', str(self.task), '--execution'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('stop-conditions', json.loads(result.stdout)['executionBrief']['task']['executionContract'])

    def test_missing_task_or_dependency_is_blocked(self):
        self.assertFalse(execution_brief(self.task, self.model, None)['gate']['canImplement'])
        self.model['edges'] = [{'from': '2', 'to': '1'}]
        self.assertIn('dependency_not_complete:2', execution_brief(self.task, self.model, '1')['gate']['blockers'])

    def test_css_hiding_content_invalidates_review(self):
        before = parse_html_plan_contract('<html><head><style>p{color:black}</style></head><body>'+self.html+'</body></html>')
        after = parse_html_plan_contract('<html><head><style>p{display:none}</style></head><body>'+self.html+'</body></html>')
        self.assertNotEqual(design_hash(before), design_hash(after))

    def test_version_and_evidence_are_required(self):
        model = parse_html_plan_contract(self.html.replace('execution-contract-version', 'unversioned'))
        self.assertIn('execution_contract_version_required:1', readiness(self.task, model)['blockers'])
        (self.task/'intent-review.md').write_text('changed review')
        self.assertIn('review_evidence_mismatch:intent', readiness(self.task, self.model)['blockers'])

    def test_plan_review_is_bound_to_intent_result(self):
        self.receipt['reviews']['intent']['basis'] = 'different intent conclusion'
        (self.task/'plan-review.json').write_text(json.dumps(self.receipt))
        self.assertIn('plan_review_not_bound_to_intent', readiness(self.task, self.model)['blockers'])

    def test_oversized_brief_fails_without_silent_truncation(self):
        model = parse_html_plan_contract(self.html.replace('then implement', 'long step '*30000))
        write_receipt(self.task, model)
        result = execution_brief(self.task, model, '1')
        self.assertIn('execution_brief_too_large', result['gate']['blockers'])
        self.assertIsNone(result['task'])

    def test_sync_rechecks_request_and_restores_previous_output(self):
        self._assert_sync_rejects_change(change_review=False)

    def test_sync_rejects_valid_receipt_replacement_and_restores_output(self):
        self._assert_sync_rejects_change(change_review=True)

    def _assert_sync_rejects_change(self, *, change_review):
        spec = importlib.util.spec_from_file_location('execution_sync_race', ROOT/'scripts/sync-roadmap.py')
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        html = ('<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<meta name="artifact-kind" content="html-plan">'
                '<meta http-equiv="Content-Security-Policy" content="' + "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'" + '">'
                '<title>Execution</title><style>body{color:black}</style></head><body>' + self.html + '</body></html>')
        (self.task/'30_plan.html').write_text(html)
        write_receipt(self.task, parse_html_plan_contract(html))
        args = (self.task, ROOT/'scripts/generate-roadmap-view.py', '3', self.task.parent, 'fixture')
        kwargs = dict(memory_root=self.task.parent, headless=True)
        code, result = sync.synchronize(*args, **kwargs)
        self.assertEqual(code, 0, result)
        previous = (self.task/'roadmap.html').read_bytes()
        original_run = subprocess.run
        def change_request(*args, **kwargs):
            result = original_run(*args, **kwargs)
            if change_review:
                path = self.task/'plan-review.json'
                receipt = json.loads(path.read_text())
                receipt['reviews']['intent']['basis'] = 'different but valid review basis'
                receipt['reviews']['plan']['intentReviewSha256'] = hashlib.sha256(json.dumps(receipt['reviews']['intent'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                path.write_text(json.dumps(receipt))
                self.assertTrue(readiness(self.task, parse_html_plan_contract(html))['canImplement'])
            else:
                (self.task/'00_request.md').write_text('changed while generator ran')
            return result
        with mock.patch.object(sync.subprocess, 'run', side_effect=change_request):
            code, result = sync.synchronize(*args, **kwargs)
        self.assertEqual(code, 2, result)
        self.assertIn('review changed', result.get('error', ''))
        self.assertEqual((self.task/'roadmap.html').read_bytes(), previous)

    def test_sync_real_gate_blocks_before_generator_and_passes_reviewed_plan(self):
        spec = importlib.util.spec_from_file_location('execution_sync', ROOT/'scripts/sync-roadmap.py')
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        generator = ROOT/'scripts/generate-roadmap-view.py'
        for phase in ('3', '4'):
            code, result = sync.synchronize(self.task, generator, phase, self.task.parent, 'fixture', memory_root=self.task.parent, dry_run=True, headless=True)
            self.assertEqual(code, 0, result)
            self.assertEqual(result['status'], 'dry_run')
        (self.task/'plan-review.json').unlink()
        for phase in ('3', '4', '5'):
            code, result = sync.synchronize(self.task, generator, phase, self.task.parent, 'fixture', memory_root=self.task.parent, dry_run=True, headless=True)
            self.assertEqual(code, 2)
            self.assertEqual(result['reason'], 'plan_execution_blocked')
        self.assertFalse((self.task/'roadmap.html').exists())

if __name__ == '__main__':
    unittest.main()
