"""Complete database + photo asset backup; no credentials or previous backups."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
from uuid import uuid4
import zipfile

if __package__ in (None, ''):
    from backup import validate as validate_database
else:
    from .backup import validate as validate_database

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 512 * 1024 * 1024


def safe_filename(value):
    if not isinstance(value, str) or not value or Path(value).name != value or value in ('.', '..'):
        raise ValueError('Invalid photo asset filename')
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._' for c in value):
        raise ValueError('Invalid photo asset filename')
    return value


def asset_records(database):
    with sqlite3.connect(f'{Path(database).resolve().as_uri()}?mode=ro', uri=True) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT value FROM entities WHERE kind='photo_asset'")]


def write_bundle(database, data_dir, destination):
    validate_database(database)
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Backup destination already exists')
    files = {'studio.sqlite3': Path(database)}
    for record in asset_records(database):
        name = safe_filename(record['filename'])
        file = Path(data_dir) / 'photo-assets' / name
        if not file.is_file() or file.is_symlink():
            raise ValueError(f'Missing or unsafe photo asset: {name}')
        files['photo-assets/' + name] = file
    if sum(file.stat().st_size for file in files.values()) > MAX_BYTES:
        raise ValueError('Backup exceeds the first-release 512 MiB limit')
    manifest = {'schema': 1, 'files': {name: hashlib.sha256(file.read_bytes()).hexdigest() for name, file in files.items()}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(destination.name + '.partial')
    try:
        with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, file in files.items():
                archive.write(file, name)
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
        validate_bundle(staged)
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def create_bundle(store, destination):
    """API entry: hold SQLite writer lock across the coherent asset snapshot."""
    with store.lock, tempfile.TemporaryDirectory(prefix='photo-backup-') as directory:
        snapshot = Path(directory) / 'studio.sqlite3'
        with sqlite3.connect(snapshot) as target:
            store.conn.backup(target)
        write_bundle(snapshot, store.path, destination)


@contextmanager
def unpack_validated(source):
    with tempfile.TemporaryDirectory(prefix='photo-restore-') as directory:
        root = Path(directory)
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(names) != len(set(names)) or len(entries) > 1000 or sum(item.file_size for item in entries) > MAX_BYTES:
                raise ValueError('Oversized or duplicate backup entries')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > 1024 * 1024:
                raise ValueError('Invalid backup manifest')
            manifest = json.loads(archive.read('manifest.json'))
            hashes = manifest.get('files')
            if manifest.get('schema') != 1 or not isinstance(hashes, dict) or set(names) != set(hashes) | {'manifest.json'}:
                raise ValueError('Manifest does not match archive')
            if 'studio.sqlite3' not in hashes:
                raise ValueError('Database missing from backup')
            for name, digest in hashes.items():
                if name != 'studio.sqlite3':
                    if not name.startswith('photo-assets/'):
                        raise ValueError('Unsafe archive path')
                    safe_filename(name.removeprefix('photo-assets/'))
                info = archive.getinfo(name)
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError('Archive links are not allowed')
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                count, hasher = 0, hashlib.sha256()
                with archive.open(info) as stream, target.open('wb') as output:
                    while chunk := stream.read(1024 * 1024):
                        count += len(chunk)
                        if count > info.file_size or count > MAX_BYTES:
                            raise ValueError('Archive size mismatch')
                        output.write(chunk)
                        hasher.update(chunk)
                if count != info.file_size or hasher.hexdigest() != digest:
                    raise ValueError('Backup checksum mismatch')
            validate_database(root / 'studio.sqlite3')
            expected = {'studio.sqlite3'} | {'photo-assets/' + safe_filename(r['filename']) for r in asset_records(root / 'studio.sqlite3')}
            if expected != set(hashes):
                raise ValueError('Photo asset references do not match backup files')
        yield root


def validate_bundle(source):
    with unpack_validated(source):
        pass


def restore_bundle(source, data_dir, confirm=False):
    with unpack_validated(source) as extracted:
        if not confirm:
            raise ValueError('Validated. Stop the service and pass --confirm to restore.')
        data_dir = Path(data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        for suffix in ('-wal', '-shm'):
            if (data_dir / ('studio.sqlite3' + suffix)).exists():
                raise ValueError('Stop the service before restoring WAL data')
        preserved = data_dir / 'pre-restore' / str(uuid4())
        preserved.mkdir(parents=True)
        moved, installed = [], []
        # Copy staging onto the destination filesystem before atomic replacements.
        with tempfile.TemporaryDirectory(prefix='photo-restore-stage-', dir=data_dir) as staging:
            staged = Path(staging)
            shutil.copy2(extracted / 'studio.sqlite3', staged / 'studio.sqlite3')
            if (extracted / 'photo-assets').exists():
                shutil.copytree(extracted / 'photo-assets', staged / 'photo-assets')
            else:
                (staged / 'photo-assets').mkdir()
            try:
                for name in ('studio.sqlite3', 'photo-assets'):
                    current = data_dir / name
                    if current.exists():
                        os.replace(current, preserved / name)
                        moved.append(name)
                    os.replace(staged / name, current)
                    installed.append(name)
            except Exception:
                for name in reversed(installed):
                    current = data_dir / name
                    shutil.rmtree(current) if current.is_dir() else current.unlink(missing_ok=True)
                for name in moved:
                    os.replace(preserved / name, data_dir / name)
                raise
        return preserved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'validate', 'restore'])
    parser.add_argument('file', type=Path)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    if args.action == 'validate':
        validate_bundle(args.file)
        print('Database and all referenced photos verified.')
    elif args.action == 'restore':
        preserved = restore_bundle(args.file, args.data_dir, args.confirm)
        print(f'Restored database and photos. Previous data: {preserved}')
    else:
        database = args.data_dir.resolve() / 'studio.sqlite3'
        if not database.is_file():
            raise SystemExit('Database not found')
        with tempfile.TemporaryDirectory(prefix='photo-backup-') as directory:
            snapshot = Path(directory) / 'studio.sqlite3'
            with sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True) as source, sqlite3.connect(snapshot) as target:
                source.backup(target)
            write_bundle(snapshot, args.data_dir, args.file)
        print(f'Saved database and photos: {args.file.resolve()}')


if __name__ == '__main__':
    main()
