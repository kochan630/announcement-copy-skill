#!/usr/bin/env python3
"""Preview an image plan; execute one approved OpenAI Images request explicitly."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone

ENDPOINT = 'https://api.openai.com/v1/images/generations'
MODELS = {'gpt-image-2', 'gpt-image-1.5'}
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def load_plan(path):
    plan = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(plan, dict):
        raise ValueError('Plan must be a JSON object.')
    allowed = {'purpose', 'placement', 'concept', 'exact_text', 'generation', 'output'}
    if set(plan) != allowed:
        raise ValueError('Use exactly the fields in examples/image-plan.json.')
    for key in allowed - {'generation'}:
        if not isinstance(plan[key], str) or not plan[key].strip():
            raise ValueError('Plan text fields must be non-empty strings.')
    gen = plan['generation']
    if not isinstance(gen, dict) or set(gen) != {'model', 'size', 'quality', 'prompt'}:
        raise ValueError('generation requires model, size, quality and prompt.')
    if any(not isinstance(v, str) or not v.strip() for v in gen.values()):
        raise ValueError('Generation fields must be non-empty strings.')
    if gen['model'] not in MODELS:
        raise ValueError('Supported models: gpt-image-2, gpt-image-1.5. Check current availability before use.')
    if gen['quality'] not in {'low', 'medium', 'high', 'auto'}:
        raise ValueError('Unsupported quality.')
    size = gen['size']
    if size != 'auto':
        try:
            w, h = map(int, size.split('x'))
        except (ValueError, TypeError):
            raise ValueError('Size must be auto or WIDTHxHEIGHT.') from None
        if min(w, h) <= 0:
            raise ValueError('Image dimensions must be positive.')
        if gen['model'] == 'gpt-image-1.5':
            if size not in {'1024x1024', '1536x1024', '1024x1536'}:
                raise ValueError('Unsupported size for gpt-image-1.5.')
        elif max(w, h) > 3840 or w % 16 or h % 16 or max(w, h) > 3 * min(w, h) or not 655360 <= w * h <= 8294400:
            raise ValueError('Unsupported dimensions for gpt-image-2.')
    output = Path(plan['output']).expanduser()
    if not output.is_absolute():
        output = path.parent / output
    output = output.resolve()
    if output.suffix.lower() != '.png':
        raise ValueError('Output must have a .png extension.')
    payload = {**gen, 'n': 1, 'output_format': 'png'}
    reviewed = {'plan': plan, 'resolved_output': str(output), 'endpoint': ENDPOINT, 'payload': payload}
    digest = hashlib.sha256(encoded(reviewed)).hexdigest()
    return reviewed, digest, output


def write_record(path, record):
    # Replace only the record reserved by this execution, never another run's record.
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    temporary.replace(path)


def png_dimensions(raw):
    """Validate PNG chunk integrity and compressed image data without decoding pixels."""
    if not raw.startswith(PNG_SIGNATURE):
        raise ValueError('Response is not a PNG image.')
    offset, width, height = 8, 0, 0
    image_data = []
    ended = False
    while offset + 12 <= len(raw):
        length = struct.unpack('>I', raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(raw):
            raise ValueError('Truncated PNG chunk.')
        content = raw[offset + 8:offset + 8 + length]
        crc = struct.unpack('>I', raw[offset + 8 + length:end])[0]
        if zlib.crc32(kind + content) & 0xffffffff != crc:
            raise ValueError('PNG chunk checksum mismatch.')
        if offset == 8 and kind != b'IHDR':
            raise ValueError('Missing PNG header.')
        if kind == b'IHDR':
            if offset != 8 or length != 13:
                raise ValueError('Invalid PNG header.')
            width, height = struct.unpack('>II', content[:8])
            if min(width, height) <= 0 or width * height > 8294400:
                raise ValueError('Invalid PNG dimensions.')
        elif kind == b'IDAT':
            image_data.append(content)
        elif kind == b'IEND':
            if length or end != len(raw):
                raise ValueError('Invalid PNG ending.')
            ended = True
            break
        offset = end
    if not ended or not image_data:
        raise ValueError('Incomplete PNG image.')
    decoder = zlib.decompressobj()
    decoder.decompress(b''.join(image_data), width * height * 8 + height * 16 + 8192)
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Incomplete or oversized PNG image data.')
    return width, height


def execute(reviewed, digest, output):
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('Set OPENAI_API_KEY locally; do not paste it into chat.')
    record_path = output.with_name(output.name + '.request.json')
    if output.exists() or record_path.exists():
        raise ValueError('Output or request record already exists. Inspect the prior run before choosing a new path.')
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {'plan_sha256': digest, 'reviewed': reviewed, 'status': 'request_reserved',
              'started_at': datetime.now(timezone.utc).isoformat()}
    # Reserve a receipt before a potentially billable call. No automatic retry.
    with record_path.open('x', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    request = urllib.request.Request(ENDPOINT, data=encoded(reviewed['payload']),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            record['request_id'] = response.headers.get('x-request-id')
            data = json.load(response)
        items = data.get('data')
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise ValueError('Expected one generated image.')
        raw = base64.b64decode(items[0]['b64_json'], validate=True)
        width, height = png_dimensions(raw)
        size = reviewed['payload']['size']
        if size != 'auto' and size != f'{width}x{height}':
            raise ValueError('Returned dimensions differ from the approved plan.')
        with output.open('xb') as handle:
            handle.write(raw)
        record.update(status='completed', output_sha256=hashlib.sha256(raw).hexdigest(),
                      actual_size=f'{width}x{height}', usage=data.get('usage'))
    except Exception as error:
        # Do not print exception bodies: providers can echo sensitive request data.
        record['status'] = 'failed_or_unknown'
        record['error_type'] = type(error).__name__
        if isinstance(error, urllib.error.HTTPError):
            record['http_status'] = error.code
        write_record(record_path, record)
        raise RuntimeError('Generation failed or its completion is unknown. Inspect the request record and API account before retrying.') from None
    record['finished_at'] = datetime.now(timezone.utc).isoformat()
    write_record(record_path, record)
    return record_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--execute', action='store_true', help='Send one billable request after user approval.')
    parser.add_argument('--approved-sha256', help='Digest of the plan that the user approved.')
    args = parser.parse_args(argv)
    try:
        reviewed, digest, output = load_plan(args.plan.resolve())
        if not args.execute:
            print(json.dumps({'mode': 'preview_no_api_call', 'plan_sha256': digest,
                              'reviewed': reviewed}, ensure_ascii=False, indent=2))
            return 0
        if args.approved_sha256 != digest:
            raise ValueError('Approval digest missing or mismatched. Preview and obtain approval for this exact plan.')
        receipt = execute(reviewed, digest, output)
        print(json.dumps({'status': 'completed', 'output': str(output), 'record': str(receipt)}))
        return 0
    except (ValueError, OSError, KeyError, RuntimeError) as error:
        # ValueError text here is authored locally. Never expose raw provider errors.
        if isinstance(error, (ValueError, RuntimeError)) and not isinstance(error, json.JSONDecodeError):
            message = str(error)
        else:
            message = 'Could not read/write the plan or output; inspect local paths and the request record.'
        print(message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
