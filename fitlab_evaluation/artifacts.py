"""Bounded artifact IO and atomic, no-overwrite directory publication."""
import argparse
import ctypes
import errno
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from .grader import strict_json
from fitlab_foundation.planner_cli import _check_json_depth

class BoundedParser(argparse.ArgumentParser):
    def error(self,message):
        self.exit(2,'{"code":"INVALID_ARGUMENTS","status":"ERROR"}\n')


MAX_ARTIFACT_BYTES=16*1024*1024

class ArtifactError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def stable_json(value):
    try:
        return json.dumps(value,sort_keys=True,indent=2,ensure_ascii=True,allow_nan=False)+'\n'
    except (TypeError,ValueError,RecursionError) as exc:
        raise ArtifactError('INVALID_ARTIFACT_VALUE') from exc


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical_source_bytes(data):
    """Normalize line endings so git blob bytes and worktree bytes agree.

    The F5 evidence contract binds two independent hashes to the same source:
    ``make_trust`` hashes git blob bytes while ``run.identity`` hashes
    working-tree bytes, and the workflow refuses to run unless they match.
    A Windows checkout with CRLF worktree files and LF blobs would make every
    source file appear modified and the workflow would refuse to start.

    Hashing the canonical LF form of both sides keeps the binding exact for
    real content changes while ignoring a purely transport-level difference in
    line endings. Only line endings are affected; every other byte counts.
    """
    return data.replace(b'\r\n', b'\n')


def source_digest(data):
    """Digest a source file in its canonical, line-ending-independent form."""
    return digest(canonical_source_bytes(data))


def load_json(path):
    try:
        with Path(path).open('rb') as stream:data=stream.read(MAX_ARTIFACT_BYTES+1)
    except OSError as exc:raise ArtifactError('INPUT_UNAVAILABLE') from exc
    if len(data)>MAX_ARTIFACT_BYTES:raise ArtifactError('INPUT_TOO_LARGE')
    try:
        text=data.decode('utf-8');_check_json_depth(text);value=strict_json(text)
    except (ValueError,UnicodeError,RecursionError) as exc:raise ArtifactError('INVALID_JSON') from exc
    return value,digest(data)


def _rename_new(source,destination):
    if os.name=='nt':
        os.rename(source,destination)  # Windows refuses existing destination.
    else:
        libc=ctypes.CDLL(None,use_errno=True)
        rename=getattr(libc,'renameat2',None)
        if rename is None:raise ArtifactError('ATOMIC_PUBLICATION_UNSUPPORTED')
        rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        rename.restype=ctypes.c_int
        if rename(-100,os.fsencode(source),-100,os.fsencode(destination),1):
            error=ctypes.get_errno()
            if error in (errno.EINVAL,errno.ENOSYS,errno.ENOTSUP):raise ArtifactError('ATOMIC_PUBLICATION_UNSUPPORTED')
            if error in (errno.EEXIST,errno.ENOTEMPTY):raise ArtifactError('OUTPUT_EXISTS')
            raise OSError(error,'atomic publication failed')


def publish_bundle(directory,files):
    """Expose complete directory in one atomic operation; never replace a destination."""
    destination=Path(directory)
    if os.path.lexists(destination):raise ArtifactError('OUTPUT_EXISTS')
    if not destination.parent.is_dir():raise ArtifactError('OUTPUT_PARENT_UNAVAILABLE')
    if type(files) is not dict or not files:raise ArtifactError('INVALID_BUNDLE')
    for name,body in files.items():
        if type(name) is not str or Path(name).name!=name or name in ('.','..','manifest.json') or type(body) is not str:
            raise ArtifactError('INVALID_BUNDLE')
    temporary=Path(tempfile.mkdtemp(prefix='.fitlab-',dir=destination.parent))
    try:
        manifest={'schema_version':'fitlab-bundle-v1','files':{}}
        for name,body in sorted(files.items()):
            data=body.encode('utf-8')
            if len(data)>MAX_ARTIFACT_BYTES:raise ArtifactError('OUTPUT_TOO_LARGE')
            with (temporary/name).open('xb') as handle:
                handle.write(data);handle.flush();os.fsync(handle.fileno())
            manifest['files'][name]=digest(data)
        # newline='' preserves the exact '\n' bytes stable_json emits.
        (temporary/'manifest.json').write_text(stable_json(manifest),encoding='utf-8',newline='')
        _rename_new(temporary,destination)
    except ArtifactError:raise
    except OSError as exc:raise ArtifactError('OUTPUT_IO_ERROR') from exc
    finally:
        if temporary.exists():shutil.rmtree(temporary)
    return manifest
