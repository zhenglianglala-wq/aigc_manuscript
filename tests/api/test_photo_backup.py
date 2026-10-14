import hashlib
import json
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.store import Store
from scripts.photo_backup import create_bundle, restore_bundle
from test_photos import confirmed, done, image_run

def archive_with_photo(client, destination):
    p=confirmed(client);record=done(client,image_run(client,p).json());assert record['status']=='succeeded'
    asset=client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    original=client.get(asset['download_url']).content
    create_bundle(client.app.state.store,destination)
    return p,asset,original

def test_portable_backup_restore_reopens_project_and_decodable_media(client,tmp_path):
    archive=tmp_path/'complete.zip';p,asset,original=archive_with_photo(client,archive)
    target=tmp_path/'restored'
    preserved=restore_bundle(archive,target,confirm=True)
    assert preserved.is_dir()
    with TestClient(create_app(data_dir=target)) as restored:
        assert restored.get(f"/api/photo-projects/{p['id']}").json()['prompt']==p['prompt']
        metadata=restored.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
        assert metadata['prompt_revision']==asset['prompt_revision']
        download=restored.get(asset['download_url']);assert download.status_code==200
        assert hashlib.sha256(download.content).digest()==hashlib.sha256(original).digest()
        assert restored.get(asset['preview_url']).content==original

@pytest.mark.parametrize('damage',['missing_asset','checksum','path_traversal','corrupt_zip'])
def test_invalid_bundle_cannot_partially_overwrite_existing_data(client,tmp_path,damage):
    archive=tmp_path/'complete.zip';archive_with_photo(client,archive)
    broken=tmp_path/'broken.zip'
    if damage=='corrupt_zip':broken.write_bytes(b'not zip data')
    else:
        with zipfile.ZipFile(archive) as original:entries={name:original.read(name) for name in original.namelist()}
        media=next(name for name in entries if name.startswith('photo-assets/'))
        manifest=json.loads(entries['manifest.json'])
        if damage=='missing_asset':entries.pop(media);manifest['files'].pop(media)
        elif damage=='checksum':entries[media]+=b'changed'
        else:
            entries['../escape.txt']=b'escape';manifest['files']['../escape.txt']=hashlib.sha256(b'escape').hexdigest()
        entries['manifest.json']=json.dumps(manifest).encode()
        with zipfile.ZipFile(broken,'w') as out:
            for name,data in entries.items():out.writestr(name,data)
    target=tmp_path/'target';store=Store(target)
    with store.tx():store.put('project',{'id':'preserve','title':'Original project'})
    store.conn.close();db=target/'studio.sqlite3';before=db.read_bytes()
    with pytest.raises(Exception):restore_bundle(broken,target,confirm=True)
    assert db.read_bytes()==before
    assert not (tmp_path/'escape.txt').exists() and not (target/'escape.txt').exists()
