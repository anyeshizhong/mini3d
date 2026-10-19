"""Reproduce the small, pinned Poly Haven PBR inputs; not used at runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LAYERS = (('soil', 'brown_mud_02', 1.3, 'Rob Tuytel'),
          ('rock', 'rock_face', 2.4, 'Dario Barresi (processing), Greg Zaal (photography)'),
          ('grass', 'leafy_grass', 2.0, 'Charlotte Baglioni'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(cache):
    destination = HERE/'assets/materials'
    destination.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = destination/'manifest.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    jobs = [(layer, asset, metres, author, channel, ext)
            for layer, asset, metres, author in LAYERS
            for channel, ext in (('diff','jpg'),('nor_gl','png'),('rough','png'))]
    def job(row):
        layer, asset, metres, author, channel, ext = row
        name = '{}_{}_1k.{}'.format(asset,channel,ext)
        url = 'https://dl.polyhaven.org/file/ph-assets/Textures/{}/1k/{}/{}'.format(ext,asset,name)
        source = cache/name
        if not source.exists():
            request = urllib.request.Request(url,headers={'User-Agent':'Mini3D-Terrain-Lab/1.0'})
            with urllib.request.urlopen(request,timeout=60) as response:
                data = response.read(16*1024*1024+1)
            if len(data)>16*1024*1024:
                raise ValueError('Unexpectedly large texture: '+url)
            source.write_bytes(data)
        raw = source.read_bytes()
        key = layer+'/'+channel+'.png'
        if previous:
            assert sha(raw)==previous['maps'][key]['upstream_sha256'], 'Upstream content changed: '+key
        with Image.open(source) as image:
            assert image.size == (1024,1024), (name,image.size)
            image = image.convert('RGB').resize((256,256),Image.Resampling.LANCZOS)
            if channel=='nor_gl':
                normal=np.asarray(image,dtype='float64')/127.5-1.
                normal/=np.maximum(np.linalg.norm(normal,axis=2,keepdims=True),1e-12)
                image=Image.fromarray(np.round((normal+1.)*127.5).clip(0,255).astype('uint8'))
            path=destination/key
            path.parent.mkdir(exist_ok=True)
            image.save(path)
        entry=dict(url=url,asset_page='https://polyhaven.com/a/'+asset,
                   author=author,tile_metres=metres,upstream_sha256=sha(raw),
                   upstream_bytes=len(raw),bundled_sha256=sha(path.read_bytes()),
                   size=[256,256],channels='RGB8',normal_convention='OpenGL +Y' if channel=='nor_gl' else None)
        print('Prepared '+key,flush=True)
        return key,entry
    with ThreadPoolExecutor(max_workers=3) as pool:
        maps=dict(pool.map(job,jobs))
    manifest=dict(license='CC0-1.0',license_url='https://polyhaven.com/license',
                  preparation='Pillow RGB8 decode and Lanczos 1K to 256; normal vectors renormalized after resize',maps=maps)
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=ROOT/'captures/world-surroundings/material-source')
    prepare(parser.parse_args().cache)
