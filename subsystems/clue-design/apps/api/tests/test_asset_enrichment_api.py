from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from py_lumen_config import settings
from lumen_api.main import create_app
from lumen_api.asset_enrichment import run_asset_enrichment
from lumen_ingestion import pipeline
from lumen_ingestion.describe import DescribeResult
from asset_analysis_fixture import analysis


@pytest.mark.parametrize('mime,format', [('image/png','PNG'), ('image/jpeg','JPEG'), ('image/webp','WEBP'), ('image/gif','GIF'), ('image/svg+xml','SVG')])
def test_format_custody_preview_analysis_and_overrides(mime, format, tmp_path, workspace_id, design_storage, monkeypatch):
    monkeypatch.setattr(settings, 'lumen_core_helper', str(Path(__file__).resolve().parents[3] / 'target/debug/lumen-api-helper'))
    if format == 'SVG':
        raw = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><rect width="60" height="80" fill="#003366"/></svg>'
    else:
        image = Image.new('RGB', (120,80), '#003366')
        buffer = BytesIO()
        if format in {'GIF','WEBP'}:
            image.save(buffer, format=format, save_all=True,
                       append_images=[Image.new('RGB', (120,80), '#660000')], duration=100, loop=0)
        else:
            image.save(buffer, format=format)
        raw = buffer.getvalue()
    class Describer:
        active = True
        def describe(self, items):
            return [DescribeResult(item.asset_id, 'Suggested', 'Caption', 'Usage', [],
                    analysis=analysis('Suggested', item.source_occurrences)) for item in items]
    monkeypatch.setattr(pipeline, 'resolve_describer', lambda: Describer())
    app = create_app(tmp_path / 'cache', storage=design_storage)
    # No embedded worker: exercise its production body explicitly after response assertions.
    client = TestClient(app, headers={'X-Workspace-Id': workspace_id})
    assert client.get('/assets/upload-capabilities').json()['max_bytes'] == settings.lumen_asset_max_bytes
    key = uuid4().hex
    request = {'files': {'file': (f'sample.{format.lower()}',raw,mime)},
               'data': {'creative_type':'logo','user_note':'A customer logo, not our own mark'},
               'headers': {'Idempotency-Key':key}}
    response = client.post('/assets', **request)
    assert response.status_code == 200, response.text
    body = response.json()
    aid = body['asset']['id']
    assert body['enrichment']['status'] == 'queued'
    assert client.get(f'/assets/{aid}/bytes').content == raw
    replay = client.post('/assets', **request)
    assert replay.status_code == 200, replay.text
    assert replay.json()['asset']['id'] == aid
    conflict = client.post('/assets', files=request['files'], data={'creative_type':'ad'}, headers=request['headers'])
    assert conflict.status_code == 409, conflict.text
    run_asset_enrichment(str(tmp_path / 'cache'), body['enrichment']['job_id'], workspace_id=workspace_id, storage=design_storage)
    saved = client.get('/assets/descriptions', params={'asset_ids':aid}).json()['descriptions'][aid]
    assert saved['status'] == 'ready', saved
    if format in {'GIF','WEBP'}:
        assert 'first_animation_frame_only' in saved['agent_context']['preview']['transformations']
    assert client.put(f'/assets/{aid}/description', json={'reset_fields':['not_a_field']}).status_code == 422
    assert client.put(f'/assets/{aid}/description', json={'title':'X','reset_fields':['title']}).status_code == 422
    assert saved['creative_type'] == 'logo' and saved['analysis']['creative_type'] == 'product_screenshot'
    assert saved['agent_context']['observed']['subjects'] == ['interface']
    assert client.put(f'/assets/{aid}/description', json={'title':'Human title'}).status_code == 200
    assert client.put(f'/assets/{aid}/description', json={'reset_fields':['creative_type']}).status_code == 200
    saved = client.get('/assets/descriptions', params={'asset_ids':aid}).json()['descriptions'][aid]
    assert saved['title'] == 'Human title' and saved['creative_type'] == 'product_screenshot'
    assert saved['overrides']['user_note'].startswith('A customer logo')
    foreign = TestClient(app, headers={'X-Workspace-Id': 'ws_other_asset_test'})
    assert foreign.get('/assets/descriptions', params={'asset_ids':aid}).json()['descriptions'] == {}
    assert foreign.post(f'/assets/{aid}/analysis/retry').status_code == 404
    # The engine supplies a real placement record and raster thumbnail for every advertised format.
    assert body['asset']['kind'] in {'raster_image','vector','logo'}
    thumb = client.get(f'/assets/{aid}/thumbnail')
    assert thumb.status_code == 200, thumb.text
    assert Image.open(BytesIO(thumb.content)).size[0] > 0
    # Prove placement paints the accepted format through the real engine, not only a thumbnail.
    from lumen_api.asset_custody import ensure_materialized, record_digests
    from lumen_api.design_store import DesignBlobStore, HybridRepository
    from lumen_agent.tools.asset_preview import _RASTER_PAGE_ID, _raster_page, _raster_image_node
    record = HybridRepository(workspace_id).require_asset_record(aid)['asset']
    cache = tmp_path / 'placement'
    ensure_materialized(DesignBlobStore(design_storage, workspace_id), str(cache),
                        (digest for digest, _mime in record_digests(record)))
    core = app.state.core
    scene = core.new_scene('format_check', 'Format check')
    scene['pages'] = {_RASTER_PAGE_ID: _raster_page()}
    scene['assets'] = {aid: record}
    scene = core.apply_operations(scene, [{'kind':'insert_node',
        'parent':{'kind':'page','id':_RASTER_PAGE_ID},'index':0,'node':_raster_image_node(aid)}])['scene']
    rendered = core.export_preview(scene, 'png', page_ids=[_RASTER_PAGE_ID], asset_store_root=str(cache))
    pixels = Image.open(BytesIO(bytes(rendered['export']['artifacts'][0]['bytes']))).convert('RGB')
    red, green, blue = pixels.getpixel((128, 256))
    assert red < 25 and blue > 80, (format, (red, green, blue), rendered.get('diagnostics'))
    web = core.web_new_doc('format_web', 'Format web')['web_doc']
    web['assets'] = {aid: record}
    page = web['pages'][0]['id']
    web = core.web_ingest_html(web, page, f'<section id="art"><img data-asset="{aid}" alt="Format check" /></section>')['web_doc']
    html = core.web_render(web, page, asset_base_url='https://assets.example')['html']
    assert 'https://assets.example/' in html
    assert record['media']['digest']['value'] in html
    assert '<img ' in html and 'alt="Format check"' in html


def test_enrichment_stores_an_image_vector_the_turn_can_read(tmp_path, workspace_id, design_storage, monkeypatch):
    """Hybrid asset search (2026-10-05), end to end on a real database: an uploaded image is
    enriched, the enrichment step writes its CLIP vector, a second run leaves it alone, and the
    turn-time loader reads it back for this workspace only."""
    from lumen_api import asset_embeddings

    model_dir = Path(settings.lumen_asset_embedding_model_dir or '/nonexistent').expanduser()
    if not (model_dir / 'image.onnx').is_file():
        pytest.skip('no CLIP ONNX model directory configured')
    image = Image.new('RGB', (160, 120), '#d23c3c')
    buffer = BytesIO()
    image.save(buffer, format='PNG')

    class Describer:
        active = True
        def describe(self, items):
            return [DescribeResult(item.asset_id, 'Red block', 'A plain red rectangle image.', 'Usage', [],
                    analysis=analysis('Red block', item.source_occurrences)) for item in items]

    monkeypatch.setattr(pipeline, 'resolve_describer', lambda: Describer())
    app = create_app(tmp_path / 'cache', storage=design_storage)
    client = TestClient(app, headers={'X-Workspace-Id': workspace_id})
    body = client.post('/assets', files={'file': ('red.png', buffer.getvalue(), 'image/png')},
                       data={'creative_type': 'background'}, headers={'Idempotency-Key': uuid4().hex}).json()
    aid = body['asset']['id']
    run_asset_enrichment(str(tmp_path / 'cache'), body['enrichment']['job_id'], workspace_id=workspace_id, storage=design_storage)

    vectors = asset_embeddings.load_workspace_embeddings(workspace_id)
    assert list(vectors) == [aid] and len(vectors[aid]) == 512
    assert abs(sum(x * x for x in vectors[aid]) - 1) < 1e-3
    red = asset_embeddings.embed_query('a plain red rectangle')
    blue = asset_embeddings.embed_query('a photo of a blue ocean')
    import numpy as np
    v = np.array(vectors[aid], np.float32)
    assert float(v @ red) > float(v @ blue)
    stranger = f'ws_never_{uuid4().hex[:12]}'
    assert asset_embeddings.load_workspace_embeddings(stranger) == {}
    # Loading vectors is a read: it must not create the unknown workspace's row.
    from sqlalchemy import text
    from lumen_api.design_store import DesignStoreBridge

    async def exists(conn):
        return (await conn.execute(text('SELECT 1 FROM workspace WHERE workspace_id = :w'), {'w': stranger})).first()

    assert DesignStoreBridge(stranger, ensure_workspace=False)._run(exists) is None


def _png(colour: str) -> bytes:
    buffer = BytesIO()
    Image.new('RGB', (64, 48), colour).save(buffer, format='PNG')
    return buffer.getvalue()


def test_partial_enrichment_completes_with_gaps_not_failed(tmp_path, workspace_id, design_storage, monkeypatch):
    """Spec 2026-10-25 §5.1: some assets analysed, some not, is a finished job WITH GAPS — not a
    failure that hides the ones that did succeed."""
    from uuid import uuid4 as _uuid4

    from clue_design.enums import DesignIngestionKind
    from clue_design.envelopes import DesignIngestionEnvelope
    from clue_design.ingestion import new_id
    from lumen_api.asset_enrichment import offer_retry
    from lumen_ingestion.jobs import IngestionJobStore

    class Good:
        active = True
        def describe(self, items):
            return [DescribeResult(item.asset_id, 'Ok', 'Ok', 'Ok', [],
                    analysis=analysis('Ok', item.source_occurrences)) for item in items]

    class FailsForSecond(Good):
        def describe(self, items):
            if items[0].asset_id == second:
                raise RuntimeError('provider_refused:openrouter:auth_invalid')
            return super().describe(items)

    monkeypatch.setattr(pipeline, 'resolve_describer', lambda: Good())
    app = create_app(tmp_path / 'cache', storage=design_storage)
    client = TestClient(app, headers={'X-Workspace-Id': workspace_id})
    uploaded = []
    for colour in ('#003366', '#663300'):
        response = client.post('/assets', files={'file': (f'{colour[1:]}.png', _png(colour), 'image/png')},
                               data={'creative_type': 'logo'}, headers={'Idempotency-Key': _uuid4().hex})
        assert response.status_code == 200, response.text
        uploaded.append(response.json())
    first, second = (body['asset']['id'] for body in uploaded)
    run_asset_enrichment(str(tmp_path / 'cache'), uploaded[0]['enrichment']['job_id'],
                         workspace_id=workspace_id, storage=design_storage)

    monkeypatch.setattr(pipeline, 'resolve_describer', lambda: FailsForSecond())
    run_asset_enrichment(str(tmp_path / 'cache'), uploaded[1]['enrichment']['job_id'],
                         workspace_id=workspace_id, storage=design_storage)
    job_id, work_id = new_id('ingest'), _uuid4()
    envelope = DesignIngestionEnvelope(work_id=work_id, workspace_id=workspace_id, kind='ingestion',
                                       job_id=job_id, ingestion_kind=DesignIngestionKind.ASSET_ENRICHMENT,
                                       ).model_dump(mode='json')
    offer_retry(workspace_id, {'targets': {first: {}, second: {}}}, job_id=job_id, work_id=work_id,
                envelope=envelope)
    run_asset_enrichment(str(tmp_path / 'cache'), job_id, workspace_id=workspace_id, storage=design_storage)

    job = IngestionJobStore(workspace_id=workspace_id).require(job_id)
    assert job['status'] == 'succeeded_with_gaps', job
    assert job['error'] is None
    assert job['evidence']['gaps'] == [{'area': 'descriptions', 'failed': 1, 'reason': 'analysis failed'}]
