"""Exercise the original ScribbleAI demo UI's Azure HTTP endpoints."""
from fastapi.testclient import TestClient
from demo import app as demo


class Model:
    def num_parameters(self):
        return 3750000


class Vocab:
    chars = ['a', 'b']
    blank = 2
    size = 3


class FakeRecognizer:
    epoch = 1
    best_cer = 0.1
    vocab = Vocab()
    model = Model()

    def available_modes(self):
        return ['greedy']

    def recognize(self, strokes, mode, beam_width):
        return {'text': 'a', 'frames': 2,
                'ms': {'preprocess': 1.0, 'model': 2.0, 'decode': 3.0, 'total': 6.0},
                'ink': [[[0, 0], [1, 1]]], 'all': {}}


def test_original_ui_and_trace_dashboard():
    demo.LOG.clear()
    demo.TRACES.clear()
    with TestClient(demo.create_app(FakeRecognizer(), 'finetuned/model.pt')) as client:
        assert 'ScribbleAI live demo' in client.get('/').text
        assert 'ScribbleAI: dashboard' in client.get('/dashboard').text
        assert client.get('/space-bg.jpg').status_code == 200
        assert client.get('/api/info').json()['default_model'] == 'finetuned'
        assert client.get('/api/health').json()['status'] == 'ok'
        result = client.post('/api/recognize', json={'strokes': [[[0, 0], [1, 1]]]}).json()
        assert result['text'] == 'a'
        stats = client.get('/api/stats').json()
        assert stats['count'] == 1
        rid = stats['recent'][0]['id']
        assert client.get(f'/api/trace/{rid}').json()['ink']
        client.post('/api/stats/reset')
        assert client.get('/api/stats').json()['count'] == 0
