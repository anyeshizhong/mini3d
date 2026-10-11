"""Original procedural Roman soldier: a reusable bronze/painted study figurine.

This is NOT the unbundled Sketchfab museum scan. Geometry and materials are
created here so the sunset example works on a fresh clone, without asset login.
Z-up, metres, front=-Y. Meshes share the normal Mini3D PBR/shadow/capture path.
"""
import math
import numpy as np
from .scene import Entity, Mesh


def material(color, metal=0., rough=.5):
    return dict(pbrMetallicRoughness=dict(baseColorFactor=[*color,1.],
                metallicFactor=metal,roughnessFactor=rough),doubleSided=True)

BRONZE=material([.32,.18,.075],.75,.43)
GOLD=material([.58,.35,.105],.8,.35)
STEEL=material([.22,.24,.24],.8,.37)
DARK=material([.018,.014,.009],.2,.68)
RED=material([.22,.009,.014],0.,.83)
LEATHER=material([.055,.026,.012],0.,.77)
WOOD=material([.09,.047,.016],0.,.78)


class Builder:
    def __init__(self):
        self.root=Entity(name='Proud Roman Soldier (original study model)')
        self.root.placement_type='character'; self.root.keep_upright=True
        self.root.asset_path='builtin:roman-soldier'

    def mesh(self,name,vertices,faces,mat,normals=None):
        entity=Entity(Mesh(vertices,faces,normals=normals,material=mat),name)
        self.root.add_child(entity)
        return entity

    def grid(self,name,points,mat,wrap=False):
        points=np.asarray(points); rows,cols=points.shape[:2]; faces=[]
        for j in range(rows-1):
            for i in range(cols if wrap else cols-1):
                k=(i+1)%cols;a=j*cols+i;b=j*cols+k;c=(j+1)*cols+i;d=(j+1)*cols+k
                faces.extend([[a,b,d],[a,d,c]])
        return self.mesh(name,points.reshape(-1,3),faces,mat)

    def ellipsoid(self,name,center,radii,mat,rows=22,cols=40,phi=(0,math.pi),deform=None):
        center=np.asarray(center); radii=np.asarray(radii); points=[]
        for p in np.linspace(*phi,rows):
            ring=[]
            for t in np.arange(cols)*2*math.pi/cols:
                q=center+radii*np.array([math.sin(p)*math.cos(t),math.sin(p)*math.sin(t),math.cos(p)])
                if deform is not None:q=deform(q,t,p)
                ring.append(q)
            points.append(ring)
        return self.grid(name,points,mat,True)

    def rod(self,name,a,b,radius,mat,cols=16,end_radius=None):
        a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float);v=b-a;v/=np.linalg.norm(v)
        axis=np.eye(3)[np.argmin(np.abs(v))];u=np.cross(v,axis);u/=np.linalg.norm(u);w=np.cross(v,u)
        rs=(radius,radius if end_radius is None else end_radius); vertices=[]
        for p,r in zip((a,b),rs):
            for t in np.arange(cols)*2*math.pi/cols:vertices.append(p+r*(u*math.cos(t)+w*math.sin(t)))
        vertices.extend([a,b]);faces=[]
        for i in range(cols):
            k=(i+1)%cols;faces.extend([[i,k,cols+k],[i,cols+k,cols+i],
                                    [2*cols,k,i],[2*cols+1,cols+i,cols+k]])
        return self.mesh(name,vertices,faces,mat)

    def curve(self,name,points,radius,mat):
        for i,(a,b) in enumerate(zip(points,points[1:])):self.rod(name+str(i),a,b,radius,mat,cols=8)

    def band(self,name,z,height,rx,ry,mat):
        points=[]
        for zz,s in ((z,1.015),(z+height*.12,1.018),(z+height*.85,1.),(z+height, .98)):
            points.append([[rx*s*math.cos(t),ry*s*math.sin(t),zz] for t in np.arange(64)*2*math.pi/64])
        return self.grid(name,points,mat,True)


def create_roman_soldier():
    b=Builder()
    # Weight on the rear leg, open chest, raised chin, spear held upright.
    for side,y in ((-1,-.025),(1,.075)):
        hip=np.array([side*.13,y, .97]);knee=np.array([side*.15,y-.015,.59]);ankle=np.array([side*.17,y,.115])
        b.rod('Thigh',knee,hip,.091,BRONZE,end_radius=.095,cols=28)
        b.ellipsoid('Knee',knee,[.069,.07,.075],BRONZE)
        b.rod('Calf',ankle,knee,.042,BRONZE,end_radius=.063,cols=28)
        b.ellipsoid('Greave',(side*.166,y-.033,.35),[.053,.038,.208],GOLD)
        b.ellipsoid('Foot',(side*.17,y-.055,.059),[.064,.128,.055],BRONZE)
        b.ellipsoid('Sandal sole',(side*.17,y-.056,.022),[.068,.135,.019],LEATHER)
        for z in (.125,.16,.21):
            b.band('Ankle leather strap',z,.015,.047,.053,LEATHER).pos=np.array([side*.17,y,0.])
        for offset in (-.04,.012,.062):
            b.rod('Sandal strap',(side*.17-.052,y+offset,.071),
                  (side*.17+.052,y+offset,.071),.008,LEATHER)
    b.band('Red tunic',.79,.28,.235,.145,RED)
    for i in range(24):
        t=2*math.pi*i/24; xx,yy=.23*math.cos(t),.147*math.sin(t)
        tangent=np.array([-math.sin(t),math.cos(t),0.])*.022
        p=np.array([xx,yy,1.02]);q=np.array([xx*1.14,yy*1.16,.785+.022*math.cos(t*3)])
        b.mesh('Leather pteruges',[p-tangent,p+tangent,q+tangent,q-tangent],[[0,1,2],[0,2,3]],LEATHER)
        b.ellipsoid('Skirt brass stud',p+[0,0,-.035],[.009,.009,.009],GOLD,rows=8,cols=12)
    # Overlapping lorica segmentata: curved iron plates, rolled brass edges.
    for i in range(6):
        z=1.04+i*.074;rx=.228+i*.0035;ry=.137+i*.003
        b.band('Lorica overlapping plate',z,.079,rx,ry,STEEL)
        b.band('Plate rolled edge',z,.009,rx*1.019,ry*1.02,GOLD)
        for x in (-.065,.065):
            y=-ry*math.sqrt(1-(x/rx)**2)-.008
            b.ellipsoid('Lorica fastening rivet',(x,y,z+.031),[.009,.006,.009],GOLD,rows=8,cols=12)
    b.band('Waist belt',1.036,.043,.24,.151,LEATHER)
    b.mesh('Belt brass clasp',[[-.038,-.16,1.038],[.038,-.16,1.038],[.038,-.16,1.077],[-.038,-.16,1.077]],[[0,1,2],[0,2,3]],GOLD)
    b.ellipsoid('Chest upper shell',(0,.008,1.47),[.25,.153,.12],STEEL)
    for side in (-1,1):
        for i in range(3):
            b.ellipsoid('Layered shoulder plate',(side*(.215+i*.022),.0,1.47-i*.03),[.10,.148,.038],STEEL)
        b.ellipsoid('Shoulder rivet',(side*.26,-.145,1.46),[.012,.006,.012],GOLD,rows=10,cols=16)
    # Hands and muscular arms, rather than stick-shaped limbs.
    arms=[((-.27,0,1.45),(-.36,-.055,1.18),(-.44,-.12,1.08)),
          ((.27,0,1.45),(.365,-.025,1.19),(.50,-.13,1.36))]
    for shoulder,elbow,wrist in arms:
        b.rod('Upper arm',elbow,shoulder,.053,BRONZE,end_radius=.073,cols=28)
        b.ellipsoid('Elbow',elbow,[.055,.052,.053],BRONZE)
        b.rod('Forearm',wrist,elbow,.039,BRONZE,end_radius=.055,cols=28)
        b.ellipsoid('Hand',wrist,[.045,.037,.058],BRONZE)
        for f in range(4):
            p=np.asarray(wrist)+[.022,-.027,-.028+f*.016]
            b.rod('Curled fingers',p,p+[.04,-.016,.0],.007,BRONZE,cols=10)
    b.rod('Neck',(0,0,1.51),(0,-.008,1.69),.061,BRONZE,end_radius=.055,cols=32)
    # High-density facial surface with cheekbones, sockets, brow and nose.
    head_center=np.array([0.,-.012,1.77]);start=len(b.root.children)
    def face(q,t,p):
        x,y,z=q;front=max(-math.sin(t),0.)**12
        gauss=lambda xx,zz,sx,sz: math.exp(-((x-xx)/sx)**2-((z-zz)/sz)**2)
        nose=.027*gauss(0,1.765,.019,.06)+.022*gauss(0,1.74,.020,.016)
        chin=.007*gauss(0,1.659,.035,.025)
        cheeks=.009*(gauss(.054,1.745,.027,.031)+gauss(-.054,1.745,.027,.031))
        brows=.009*(gauss(.04,1.808,.027,.011)+gauss(-.04,1.808,.027,.011))
        sockets=.010*(gauss(.039,1.787,.022,.010)+gauss(-.039,1.787,.022,.010))
        q[1]-=front*(nose+chin+cheeks+brows-sockets)
        if z<1.73:q[0]*=.85+.15*np.clip((z-1.63)/.10,0,1)
        return q
    b.ellipsoid('Sculpted face',head_center,[.086,.077,.135],BRONZE,rows=96,cols=128,deform=face)
    for side in (-1,1):
        b.ellipsoid('Ear',(side*.084,-.01,1.769),[.017,.011,.032],BRONZE)
        b.ellipsoid('Eye',(side*.038,-.083,1.787),[.015,.007,.0065],BRONZE,rows=12,cols=24)
        b.ellipsoid('Eye pupil',(side*.038,-.089,1.788),[.003,.002,.003],DARK,rows=10,cols=16)
        b.curve('Raised eyelid',[(side*.023,-.088,1.788),(side*.038,-.091,1.794),
                                (side*.054,-.084,1.789)],.0018,BRONZE)
        b.curve('Brow',[(side*.021,-.085,1.809),(side*.043,-.083,1.813),
                       (side*.06,-.072,1.808)],.003,BRONZE)
        b.ellipsoid('Nostril',(side*.012,-.103,1.735),[.004,.002,.0027],DARK,rows=10,cols=16)
    b.curve('Mouth',[(-.025,-.082,1.703),(-.01,-.09,1.705),(0,-.092,1.704),
                     (.012,-.089,1.706),(.024,-.08,1.707)],.0018,DARK)
    b.curve('Lower lip',[(-.017,-.084,1.698),(0,-.089,1.697),(.018,-.083,1.701)],.0025,BRONZE)
    # Imperial helmet with neck guard, cheek guards and central red crest.
    b.ellipsoid('Helmet dome',(0,.004,1.825),[.103,.101,.115],STEEL,phi=(0,math.pi*.55))
    for angle in np.linspace(-math.pi*.1,math.pi*1.1,48):
        b.ellipsoid('Helmet lower beading',(.103*math.cos(angle),.101*math.sin(angle),1.81),
                    [.006,.006,.006],GOLD,rows=6,cols=8)
    b.ellipsoid('Neck guard',(0,.091,1.784),[.143,.051,.016],STEEL)
    for side in (-1,1):
        vertices=[[side*.096,-.016,1.819],[side*.09,-.071,1.803],
                  [side*.061,-.074,1.669],[side*.092,-.026,1.699]]
        b.mesh('Helmet cheek guard',vertices,[[0,1,2],[0,2,3]],GOLD)
        b.ellipsoid('Cheek guard hinge',(side*.098,-.019,1.813),[.008,.008,.008],GOLD,rows=10,cols=16)
    b.curve('Helmet eyebrow guard',[(x,-.107*math.sqrt(max(.01,1-(x/.105)**2)),1.828)
                                   for x in np.linspace(-.097,.097,25)],.007,GOLD)
    for i,t in enumerate(np.linspace(-1.1,1.05,70)):
        y=.122*math.sin(t);z=1.833+.133*math.cos(t)
        b.rod('Crest bristles',(-.013,y,z),(-.013,y*1.32,z+.083),.0035,RED,cols=6)
        b.rod('Crest bristles',(.013,y,z),(.013,y*1.32,z+.083),.0035,RED,cols=6)
        b.rod('Crest brass holder',(-.018,y,z),(.018,y,z),.006,GOLD,cols=8)
    # Tilt the complete head and helmet together: the chin is proudly lifted.
    head=Entity(name='Raised chin');head.pos=head_center
    head.rot=np.array([math.radians(-7),0,math.radians(-5)])
    for node in list(b.root.children[start:]):
        node.pos=-head_center
        head.add_child(node)
    b.root.add_child(head)
    # Draped burgundy cloak; folds are geometry and cast real shadows.
    points=[]
    for v in np.linspace(0,1,38):
        ring=[]
        for u in np.linspace(-1,1,45):
            x=u*(.26+.065*v)+.08*v*v
            y=.15+.11*v+.042*math.sin(u*math.pi*5+v*.8)*(v*.75+.25)
            z=1.51-v*(1.05+.075*math.cos(u*math.pi))
            ring.append([x,y,z])
        points.append(ring)
    b.grid('Heavy folded cloak',points,RED)
    b.ellipsoid('Cloak clasp',(.19,-.142,1.493),[.016,.008,.016],GOLD,rows=12,cols=20)
    # Tall pilum and its tapered iron point.
    b.rod('Pilum shaft',(.526,-.145,.025),(.526,-.145,2.02),.011,WOOD,cols=20)
    b.rod('Pilum iron shank',(.526,-.145,1.97),(.526,-.145,2.34),.007,STEEL,cols=16)
    b.rod('Pilum point',(.526,-.145,2.29),(.526,-.145,2.40),.022,STEEL,cols=4,end_radius=.0005)
    # Curved rectangular scutum with rolled rim, boss and brass wing emblems.
    cx,cy,cz=-.46,-.20,.805;hw,hh=.232,.436
    def surface(x,z,offset=0):return [cx+x,cy+.12*(x/hw)**2+offset,cz+z]
    points=[[surface(x,z) for x in np.linspace(-hw,hw,36)] for z in np.linspace(-hh,hh,46)]
    b.grid('Curved crimson scutum',points,RED)
    for z in (-hh,hh):b.curve('Scutum top rim',[surface(x,z,-.003) for x in np.linspace(-hw,hw,30)],.012,GOLD)
    for x in (-hw,hw):b.curve('Scutum side rim',[surface(x,z,-.003) for z in np.linspace(-hh,hh,30)],.012,GOLD)
    b.ellipsoid('Shield iron boss',(cx,cy-.048,cz),[.068,.055,.078],STEEL,rows=28,cols=40)
    for side in (-1,1):
        for vertical in (-1,1):
            for f in range(8):
                a=np.array([side*.055,vertical*(.055+f*.012)])
                q=np.array([side*(.14+.042*f/7),vertical*(.11+f*.029)])
                p=[surface(*a,-.004),surface(*q,-.004),surface(q[0]-side*.03,q[1]+vertical*.022,-.004),
                   surface(a[0],a[1]+vertical*.018,-.004)]
                b.mesh('Scutum brass wing feather',p,[[0,1,2],[0,2,3]],GOLD)
            for f in range(3):
                z=vertical*(.18+f*.07);x=side*.03
                b.mesh('Scutum lightning', [surface(x-.014,z-.04,-.004),surface(x+.014,z+.003,-.004),
                           surface(x,z+.025,-.004),surface(x+.022,z+.055,-.004)],[[0,1,2],[1,3,2]],GOLD)
    # Gladius carried by the belt.
    b.rod('Gladius scabbard',(.19,.11,.72),(.27,.08,1.06),.027,LEATHER,cols=12)
    b.rod('Gladius grip',(.27,.08,1.06),(.29,.075,1.17),.015,WOOD,cols=16)
    b.rod('Gladius guard',(.225,.08,1.062),(.315,.08,1.042),.009,GOLD)
    b.ellipsoid('Gladius pommel',(.29,.075,1.175),[.025,.02,.025],GOLD)
    b.root.update_transform()
    return b.root
