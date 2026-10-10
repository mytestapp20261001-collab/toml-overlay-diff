import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(HERE.name.replace("-", "_"), HERE / "tool.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

class CommonTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / "tool.py"), *args], cwd=HERE,
                              capture_output=True, text=True, timeout=10)
    def test_cli_pass(self):
        result = self.cli("examples/" + PASS, *ARGS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "pass")
        self.assertEqual(result.stderr, "")
    def test_cli_fail(self):
        result = self.cli("examples/" + FAIL, *ARGS)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "fail")
    def test_cli_malformed(self):
        result = self.cli("examples/" + MALFORMED, *ARGS)
        self.assertEqual(result.returncode, MALFORMED_CODE, result.stdout + result.stderr)
        self.assertIn(json.loads(result.stdout)["status"], ("fail", "error"))
    def test_cli_missing_file(self):
        result = self.cli("nonexistent-input", *ARGS)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["error"], "unreadable_utf8_input")
    def test_cli_invalid_arguments_are_redacted(self):
        result = self.cli("--unrecognized-secret-value")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["error"], "invalid_arguments")
        self.assertNotIn("unrecognized-secret-value", result.stdout + result.stderr)
    def test_cli_help(self):
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage:", result.stdout)
    def test_cli_stability(self):
        a = self.cli("examples/" + FAIL, *ARGS)
        b = self.cli("examples/" + FAIL, *ARGS)
        self.assertEqual(a.stdout, b.stdout)
    def test_file_limit_and_utf8(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "input"
            path.write_bytes(b"x" * (tool.MAX_BYTES + 1))
            with self.assertRaises(tool.InputError):
                tool.read_text(path)
            path.write_bytes(b"\xff")
            with self.assertRaises(UnicodeDecodeError):
                tool.read_text(path)
    def test_json_parser_safety(self):
        for text in ('{"x":1,"x":2}', '[NaN]', '[' * 130 + '0' + ']' * 130):
            with self.subTest(text=text[:20]), self.assertRaises(tool.InputError):
                tool.parse_json(text)
    def test_report_cap_preserves_count(self):
        report = tool.Report("test")
        for i in range(101):
            report.add("sample", record=i)
        result = report.finish()
        self.assertEqual(len(result["findings"]), 100)
        self.assertEqual(result["summary"]["finding_count"], 101)
        self.assertTrue(result["findings_truncated"])

    def test_adversarial_cli_and_read_only_corpus(self):
        samples = ['', 'null', 'true', '0', '[]', '{}', '[null]', '[true]', '[1]',
                   '["NaN"]', '[{}]', '[[]]', '{"x":1,"x":2}',
                   '[1e99999999999999999999999999]', '[NaN]', '[Infinity]',
                   '"\\ud800"', '["\\ud800"]', '{', '[', '["a","b"]',
                   '[1e-99999999999999999999999999]']
        before = {path: path.read_bytes() for path in (HERE / 'examples').iterdir()}
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / 'input.txt'
            for sample in samples:
                with self.subTest(sample=sample):
                    path.write_text(sample, encoding='utf-8')
                    result = self.cli(str(path), *ARGS)
                    self.assertIn(result.returncode, (0, 1, 2), result.stderr)
                    self.assertEqual(result.stderr, '')
                    self.assertIn(json.loads(result.stdout)['status'], ('pass','fail','error'))
                    self.assertEqual(path.read_text(encoding='utf-8'), sample)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

PASS = 'pass.toml'
FAIL = 'fail.toml'
MALFORMED = 'malformed.toml'
MALFORMED_CODE = 2
ARGS = ['--overlay', 'examples/overlay.toml', '--mode', 'deep']

class AuditTests(unittest.TestCase):
    def test_deep_retains_siblings(self):
        result=tool.audit('[x]\na=1\nb=2','[x]\na=1',mode='deep')
        self.assertEqual(result['status'],'pass')
    def test_shallow_drops_siblings(self):
        result=tool.audit('[x]\na=1\nb=2','[x]\na=1',mode='shallow')
        self.assertEqual(result['findings'][0]['code'],'removed')
        self.assertEqual(result['findings'][0]['path_indices'],[1,2])
    def test_arrays_replace_atomically(self):
        result=tool.audit('x=[1,2]','x=[1]',mode='deep')
        self.assertEqual(result['summary']['changed_locations'],1)
    def test_type_change(self):
        self.assertEqual(tool.audit('x=1','x=1.0',mode='deep')['findings'][0]['code'],'type_changed')
    def test_addition(self): self.assertEqual(tool.audit('','x=1',mode='deep')['findings'][0]['code'],'added')
    def test_no_deletion_sentinel(self):
        self.assertEqual(tool.audit('x=1','',mode='deep')['status'],'pass')
    def test_nan_equal(self): self.assertEqual(tool.audit('x=nan','x=nan',mode='deep')['status'],'pass')
    def test_malformed(self):
        with self.assertRaises(tool.InputError): tool.audit('x=1\nx=2','',mode='deep')
    def test_explicit_mode(self):
        with self.assertRaises(tool.InputError): tool.audit('','',mode='guess')
    def test_paths_opt_in(self):
        hidden=tool.audit('secret="SUPERSECRET"','secret="other"',mode='deep')
        self.assertNotIn('secret',json.dumps(hidden))
        shown=tool.audit('"a/b"=1','"a/b"=2',mode='deep',show_paths=True)
        self.assertEqual(shown['findings'][0]['path'],'/a~1b')
    def test_empty(self): self.assertEqual(tool.audit('','',mode='shallow')['status'],'pass')
    def test_nested_depth_bound(self):
        text='x='+ ('{a='*66) + '1' + '}'*66
        with self.assertRaises(tool.InputError): tool.parse_toml(text)

if __name__ == '__main__': unittest.main()
