"""Verified text exports over an already authenticated persistent SSH shell."""
import base64
import binascii
import hashlib
import os
import shlex
import zlib
from uuid import uuid4
from .model import LiteError

MAX_EXPORT_BYTES=64*1024*1024


def download_text_export(client,remote,path):
    """Return False for unsupported transports; never accept partial/corrupt data.

    Export files are immutable, uniquely named UTF-8 S-expressions, not arbitrary
    binary downloads. The GUI host owns these files. Other backends keep Bridge's
    normal transfer path. No new SSH process/authentication is needed here.
    """
    runner=getattr(client,'gui_runner',None)
    if runner is None or not getattr(runner,'persistent_shell_enabled',False):return False
    command=f"""(
file={shlex.quote(remote)}
if ! command -v sha256sum >/dev/null || ! command -v base64 >/dev/null || ! command -v gzip >/dev/null; then
  printf 'COLAYOUT_EXPORT_FALLBACK\n'
elif test -f "$file"; then
  size=$(wc -c < "$file") || exit 1
  if test "$size" -gt {MAX_EXPORT_BYTES}; then
    printf 'COLAYOUT_EXPORT_FALLBACK\n'
  else
    digest=$(sha256sum -- "$file") || exit 1
    printf 'COLAYOUT_EXPORT_GZIP_1 %s %s\n' "$size" "${{digest%% *}}"
    gzip -c < "$file" | base64 || exit 1
  fi
else
  printf 'Export file missing\n' >&2
  exit 1
fi
)"""
    result=runner.run_command(command,timeout=60)
    if result.returncode!=0:
        raise LiteError('DOWNLOAD_FAILED',result.stderr.strip() or '读取导出文件失败。')
    if result.stdout.strip()=='COLAYOUT_EXPORT_FALLBACK':return False
    try:
        header,encoded=result.stdout.split('\n',1)
        marker,size,digest=header.split()
        if marker!='COLAYOUT_EXPORT_GZIP_1' or not 0<=int(size)<=MAX_EXPORT_BYTES:raise ValueError('invalid export header')
        compressed=base64.b64decode(''.join(encoded.splitlines()),validate=True)
        inflater=zlib.decompressobj(31)
        data=inflater.decompress(compressed,int(size)+1)
        if not inflater.eof or inflater.unused_data:raise ValueError('incomplete/extra gzip stream')
        if len(data)!=int(size) or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('export size/hash mismatch')
        data.decode('utf-8')
    except (ValueError,UnicodeError,binascii.Error,zlib.error) as exc:
        raise LiteError('DOWNLOAD_FAILED','导出文件完整性校验失败；当前工作区未替换。') from exc
    temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
    return True
