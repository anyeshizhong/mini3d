"""Build labeled contact sheets, absolute differences and nearest-neighbor crops.

Raw renderer PNGs are never changed. Difference images use 4x gain, not a score.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[2]
MODES=[('Blender Eevee 64 samples','eevee'),('Mini3D 1x','mini-1x'),
       ('Mini3D 4x MSAA','mini-4x'),('Mini3D 2x SSAA reference','mini-ssaa2')]
ROIS=dict(Lantern=[('chain',(1058,270,1186,398)),('shadow',(1440,780,1568,908))],
          Avocado=[('outline',(810,135,938,263)),('shadow',(1380,810,1508,938))],
          spheres=[('reflection',(215,215,343,343)),('outline',(1440,500,1568,628))])


def sheet(panels,path,size):
    w,h=size
    canvas=Image.new('RGB',(w*len(panels),h+32),(20,20,24));draw=ImageDraw.Draw(canvas)
    for i,(label,picture) in enumerate(panels):
        draw.text((i*w+10,9),label,fill='white');canvas.paste(picture,(i*w,32))
    canvas.save(path)


def compare(output):
    records=[]
    for name in ROIS:
        pictures=[Image.open(output/(name+'-'+mode+'.png')).convert('RGB') for _,mode in MODES]
        sheet([(label,p.resize((480,270),Image.Resampling.LANCZOS))
               for (label,_),p in zip(MODES,pictures)],output/(name+'-comparison.png'),(480,270))
        arrays=[np.asarray(p).astype(np.int16) for p in pictures]
        differences=[]
        for i,j,label in [(0,1,'4 * |Eevee - 1x|'),(0,2,'4 * |Eevee - MSAA|'),(1,2,'4 * |1x - MSAA|')]:
            diff=Image.fromarray(np.clip(4*np.abs(arrays[i]-arrays[j]),0,255).astype(np.uint8))
            differences.append((label,diff.resize((640,360),Image.Resampling.NEAREST)))
        sheet(differences,output/(name+'-differences.png'),(640,360))
        for label,box in ROIS[name]:
            sheet([(title,p.crop(box).resize((512,512),Image.Resampling.NEAREST))
                   for (title,_),p in zip(MODES,pictures)],output/(name+'-'+label+'-zoom.png'),(512,512))
        source,aa=arrays[1],arrays[2];delta=np.abs(source-aa).max(axis=2)
        # Explicit high-gradient exclusion: two pixels around any >2-code RGB step.
        edges=np.zeros(delta.shape,bool)
        for axis in (0,1):
            step=np.max(np.abs(np.diff(source,axis=axis)),axis=2)>2
            if axis==0:edges[:-1]|=step;edges[1:]|=step
            else:edges[:,:-1]|=step;edges[:,1:]|=step
        padded=np.pad(edges,2)
        band=np.zeros_like(edges)
        for y in range(5):
            for x in range(5):band|=padded[y:y+1080,x:x+1920]
        coverage=np.asarray(Image.open(output/(name+'-coverage-ssaa2.png')))[:,:,0]
        interior=(coverage==255)&~band
        outside=delta[interior]
        record=dict(name=name,raw_1x_exact_q1=(output.parent/'q1'/(name+'-B.png')).read_bytes()==
                    (output/(name+'-mini-1x.png')).read_bytes(),
                    aa_changed_pixels=int((delta>0).sum()),interior_tested_pixels=int(interior.sum()),
                    interior_max_delta=int(outside.max()),interior_gt_1=int((outside>1).sum()),
                    interior_gt_3=int((outside>3).sum()),rois={label:list(box) for label,box in ROIS[name]})
        assert record['raw_1x_exact_q1'], 'Disabled AA changed the Q1 baseline'
        assert record['interior_gt_1']==0, 'Investigate unexpected interior shading changes'
        label,box=ROIS[name][1]
        if label=='shadow':
            x0,y0,x1,y1=box
            record['shadow_roi_max_aa_delta']=int(delta[y0:y1,x0:x1].max())
        records.append(record)
    (output/'comparison-results.json').write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps(records,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/renderer-v2/q2')
    compare(parser.parse_args().output.resolve())
