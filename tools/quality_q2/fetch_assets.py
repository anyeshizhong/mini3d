"""Fetch only the two CC0 originals used by Q2, checking pinned file hashes."""
import hashlib
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
PIN='edc7c9e67c639d230715049ee31f9a96a6babbbe'
HASHES=dict(Lantern='a79458c4b02d695187a952f23a63b8bf278e7bc3d316a3c2a314f2d6974181f1',
            Avocado='ccc9c3ce56423720b09399c2351537207cd5a65f859f9e6e2f30922762f3abd4')


if __name__=='__main__':
    for name,expected in HASHES.items():
        path=ROOT/'captures/q2-source'/name/(name+'.glb')
        if path.exists():
            data=path.read_bytes()
        else:
            url='https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/{}/Models/{}/glTF-Binary/{}.glb'.format(PIN,name,name)
            data=urllib.request.urlopen(url,timeout=60).read()
        if hashlib.sha256(data).hexdigest()!=expected:
            raise RuntimeError('Asset hash mismatch: '+name)
        if not path.exists():
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        print(path)
