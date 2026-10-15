"""Isolated real API + simulated image vendor. Never uses user credentials/network."""
import argparse
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-dir', required=True)
parser.add_argument('--port', type=int, default=8120)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
target = Path(args.data_dir).resolve()
if target == root or root in target.parents:
    raise SystemExit('Use a temporary directory outside the repository')
os.environ.update(DATA_DIR=str(target), IMAGE_API_KEY='simulated-gui-key',
                  PAID_IMAGE_CALLS_ENABLED='true', IMAGE_MODE='openai-compatible',
                  IMAGE_BASE_URL='https://image-model.invalid/v1', IMAGE_MODEL='simulated-image',
                  LLM_API_KEY='', LLM_MODE='fixture', PAID_CALLS_ENABLED='false')
sys.path.insert(0, str(root))
import httpx
import dotenv
# The isolated server must not load the user's .env at import time.
dotenv.load_dotenv = lambda *args, **kwargs: False
from PIL import Image, ImageDraw
import uvicorn

output = io.BytesIO()
image = Image.new('RGB', (1024, 1024), '#c0d5cb')
ImageDraw.Draw(image).text((100, 100), 'SIMULATED TEST IMAGE', fill='#213d35')
image.save(output, format='PNG')
calls = []

async def vendor(request):
    assert request.url.host == 'image-model.invalid' and request.method == 'POST'
    body = json.loads(request.content)
    assert body['n'] == 1
    calls.append({'model': body['model'], 'prompt': body['prompt']})
    await asyncio.sleep(.7)
    if body['model'] == 'simulated-failure':
        return httpx.Response(500, json={'error': {'message': 'simulated failure'}})
    return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(output.getvalue()).decode()}]})

original = httpx.AsyncClient
httpx.AsyncClient = lambda **kw: original(transport=httpx.MockTransport(vendor), **kw)
from backend.main import app

@app.get('/api/test/metrics')
def metrics():
    return {'simulation': True, 'generation_requests': calls}

uvicorn.run(app, host='127.0.0.1', port=args.port)
