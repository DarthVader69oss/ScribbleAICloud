"""Check the Azure ScribbleAI demo end to end."""
import argparse
import json
import math
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--url', required=True)
a = ap.parse_args()
base = a.url.rstrip('/')

def call(path, body=None):
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

health = call('/api/health')
print('health:', health)
assert health['status'] == 'ok'
info = call('/api/info')
print('model:', info['checkpoint'], 'modes:', info['modes'])
assert info['default_model'] == 'finetuned'
strokes = [[[10 + k * 3, 40 + 12 * math.sin(k / 3), k * .01, .5] for k in range(40)]]
pred = call('/api/recognize', {'strokes': strokes, 'mode': 'greedy'})
print('prediction:', repr(pred['text']), 'frames:', pred['frames'], 'ms:', round(pred['ms']['total']))
assert 'text' in pred and pred['frames'] > 0
stats = call('/api/stats')
print('dashboard count:', stats['count'])
assert stats['count'] >= 1
