import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zlib

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / 'skills/announcement-copy/scripts/generate_image.py'
spec = importlib.util.spec_from_file_location('generate_image', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.plan_path = Path(self.temp.name) / 'plan.json'
        self.plan = json.loads((ROOT / 'skills/announcement-copy/examples/image-plan.json').read_text())
        self.plan['output'] = 'result.png'
        self.save()

    def save(self):
        self.plan_path.write_text(json.dumps(self.plan), encoding='utf-8')

    def invoke(self, execute=False, digest=None):
        args = ['--plan', str(self.plan_path)]
        if execute:
            args += ['--execute', '--approved-sha256', digest or 'wrong']
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = module.main(args)
        return result, out.getvalue(), err.getvalue()

    def approved(self):
        return module.load_plan(self.plan_path)[1]

    def response(self, raw=None):
        if raw is None:
            def chunk(kind, data):
                return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
            header = struct.pack('>IIBBBBB', 1536, 1024, 8, 2, 0, 0, 0)
            pixels = zlib.compress((b'\0' + b'\0' * (1536 * 3)) * 1024)
            raw = module.PNG_SIGNATURE + chunk(b'IHDR', header) + chunk(b'IDAT', pixels) + chunk(b'IEND', b'')
        result = io.StringIO(json.dumps({'data': [{'b64_json': base64.b64encode(raw).decode()}], 'usage': {'total_tokens': 12}}))
        result.headers = {'x-request-id': 'test-request'}
        return result

    def test_preview_never_calls_api_and_needs_no_key(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(module.urllib.request, 'urlopen') as network:
            code, out, _ = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['mode'], 'preview_no_api_call')
        network.assert_not_called()
        self.assertFalse((self.plan_path.parent / 'result.png.request.json').exists())

    def test_approval_binds_context_prompt_and_output(self):
        for field in ['concept', 'output', 'prompt']:
            with self.subTest(field=field):
                before = self.approved()
                target = self.plan['generation'] if field == 'prompt' else self.plan
                target[field] += ' changed'
                if field == 'output':
                    target[field] = 'changed.png'
                self.save()
                with patch.object(module.urllib.request, 'urlopen') as network:
                    self.assertEqual(self.invoke(True, before)[0], 1)
                    network.assert_not_called()

    def test_exactly_one_request_decodes_png_and_writes_receipt(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'unit-test-secret'}), patch.object(module.urllib.request, 'urlopen', return_value=self.response()) as network:
            code, out, err = self.invoke(True, self.approved())
        self.assertEqual(code, 0, err)
        network.assert_called_once()
        request = network.call_args.args[0]
        self.assertEqual(request.full_url, module.ENDPOINT)
        self.assertEqual(json.loads(request.data)['n'], 1)
        self.assertEqual(json.loads(request.data)['output_format'], 'png')
        record = json.loads((self.plan_path.parent / 'result.png.request.json').read_text())
        self.assertEqual(record['status'], 'completed')
        self.assertEqual(record['actual_size'], '1536x1024')
        self.assertNotIn('unit-test-secret', out + err + json.dumps(record))

    def test_missing_key_is_rejected_before_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(module.urllib.request, 'urlopen') as network:
            self.assertEqual(self.invoke(True, self.approved())[0], 1)
        network.assert_not_called()

    def test_existing_outputs_and_receipts_block_paid_retry(self):
        for name in ['result.png', 'result.png.request.json']:
            with self.subTest(name=name):
                path = self.plan_path.parent / name
                path.write_text('existing')
                with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(module.urllib.request, 'urlopen') as network:
                    self.assertEqual(self.invoke(True, self.approved())[0], 1)
                network.assert_not_called()
                self.assertEqual(path.read_text(), 'existing')
                path.unlink()

    def test_timeout_is_not_retried(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(module.urllib.request, 'urlopen', side_effect=TimeoutError('secret-error-body')) as network:
            code, out, err = self.invoke(True, self.approved())
        self.assertEqual(code, 1)
        network.assert_called_once()
        self.assertNotIn('secret-error-body', out + err)
        receipt = json.loads((self.plan_path.parent / 'result.png.request.json').read_text())
        self.assertEqual(receipt['status'], 'failed_or_unknown')

    def test_http_error_body_not_exposed(self):
        error = urllib.error.HTTPError(module.ENDPOINT, 429, 'secret-body', {}, None)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(module.urllib.request, 'urlopen', side_effect=error) as network:
            code, out, err = self.invoke(True, self.approved())
        self.assertEqual(code, 1)
        network.assert_called_once()
        self.assertNotIn('secret-body', out + err)

    def test_invalid_image_is_not_saved(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(module.urllib.request, 'urlopen', return_value=self.response(b'not-an-image')):
            self.assertEqual(self.invoke(True, self.approved())[0], 1)
        self.assertFalse((self.plan_path.parent / 'result.png').exists())

    def test_bad_size_rejected_before_network(self):
        self.plan['generation']['size'] = '1200x630'
        self.save()
        with patch.object(module.urllib.request, 'urlopen') as network:
            self.assertEqual(self.invoke()[0], 1)
        network.assert_not_called()

    def test_incomplete_or_corrupted_png_rejected(self):
        raw = base64.b64decode(json.loads(self.response().getvalue())['data'][0]['b64_json'])
        for broken in [raw[:24], raw[:-12], raw[:45] + bytes([raw[45] ^ 1]) + raw[46:]]:
            with self.subTest(length=len(broken)):
                with self.assertRaises(ValueError):
                    module.png_dimensions(broken)


if __name__ == '__main__':
    unittest.main()
