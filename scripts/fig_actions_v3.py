import os, math
from PIL import Image, ImageDraw, ImageFont
ROOT=r"e:\DeskTop\knitting_pattern_generator"; OUT=os.path.join(ROOT,"outputs","fig_actions_proto")
os.makedirs(OUT,exist_ok=True); F=r"C:\Windows\Fonts"; SS=2
def s(v): return v*SS
def font(sz,bold=False,ital=False):
    fn="timesbd.ttf" if bold else ("timesi.ttf" if ital else "times.ttf")
    return ImageFont.truetype(os.path.join(F,fn),s(sz))
PAGE=(233,242,250); CARD=(255,255,255); BORDER=(214,228,242); NAVY=(31,56,100)
TEAL=(52,168,166); MAG=(230,0,126); GRAY=(150,158,168); WHITE=(255,255,255); DASH=(50,50,50)
FAM=[("knit","Knit","f_knit / b_knit","New loop is drawn through the loop below."),
     ("tuck","Tuck","f_tuck / b_tuck","Old loop retained; a new yarn is tucked."),
     ("miss","Miss","miss","Needle not selected; no new loop formed."),
     ("xfer","Transfer","xfer_l1 / xfer_f_b","A loop moves to an adjacent needle or bed."),
     ("split","Split","f_split / b_split","A loop is divided for support / transition."),
     ("carrier","Drop-off","carrier","Loop support removed at this wale (bind-off).")]
def cr(pts,seg=14):
    P=list(pts); out=[]
    for i in range(len(P)-1):
        p0=P[max(i-1,0)];p1=P[i];p2=P[i+1];p3=P[min(i+2,len(P)-1)]
        for j in range(seg):
            t=j/seg;t2=t*t;t3=t2*t
            x=.5*(2*p1[0]+(-p0[0]+p2[0])*t+(2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2+(-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
            y=.5*(2*p1[1]+(-p0[1]+p2[1])*t+(2*p0[1]-5*p1[1]+4*p2[1]-3*p2[1]+p3[1])*t2+(-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
            out.append((x,y))
    out.append(P[-1]);return out
def arch(d,cx,ytop,w,h,color,t,dot=True):
    pts=[(cx-w*.68,ytop+h),(cx-w*.50,ytop+h*.80),(cx-w/2,ytop+h*.52)]
    hc=ytop+w/2
    for i in range(13):
        th=math.pi*(1-i/12.0)
        pts.append((cx+(w/2)*math.cos(th),hc-(w/2)*math.sin(th)))
    pts+=[(cx+w/2,ytop+h*.52),(cx+w*.50,ytop+h*.80),(cx+w*.68,ytop+h)]
    d.line(pts,fill=color,width=t,joint="curve")
    if dot:
        r1=t*1.5; r2=t*.8
        d.ellipse([cx-r1,ytop-r1,cx+r1,ytop+r1],fill=color)
        d.ellipse([cx-r2,ytop-r2,cx+r2,ytop+r2],fill=WHITE)
def curve(d,pts,color,w): d.line(cr(pts),fill=color,width=w,joint="curve")
def row_loops(d,cxc,ytop,n,u,color,wall,ov=.30):
    w=u*.48; step=w*(1-ov); total=step*(n-1)+w
    for i in range(n): arch(d,cxc-total/2+w/2+i*step,ytop,w,u,color,wall)
def arrow(d,x1,y1,x2,y2,color,w,hs):
    d.line([x1,y1,x2,y2],fill=color,width=w)
    a=math.atan2(y2-y1,x2-x1)
    for t in (a+math.radians(150),a-math.radians(150)):
        d.line([x2,y2,x2+hs*math.cos(t),y2+hs*math.sin(t)],fill=color,width=w)
def dashed(d,box,color,w,dlen=None):
    dlen=dlen or max(4,w*3)
    x0,y0,x1,y1=box
    for (ax,ay,bx,by) in [(x0,y0,x1,y0),(x1,y0,x1,y1),(x1,y1,x0,y1),(x0,y1,x0,y0)]:
        L=math.hypot(bx-ax,by-ay); n=max(1,int(L/dlen))
        for k in range(0,n,2):
            t0=k/n; t1=min(1,(k+1)/n)
            d.line([ax+(bx-ax)*t0,ay+(by-ay)*t0,ax+(bx-ax)*t1,ay+(by-ay)*t1],fill=color,width=w)
W,H=s(1800),s(1020)
img=Image.new("RGB",(W,H),PAGE); d=ImageDraw.Draw(img)
m=s(26); gap=s(22); top0=s(18)
cw=(W-2*m-2*gap)/3; ch=(H-top0-m-gap)/2
def lattice(x,y,w,h,spec,u):
    rows,cols=3,5
    xs=[x+w*(c+.5)/cols for c in range(cols)]
    ys=[y+h*(r+.5)/rows for r in range(rows)]
    nr=max(s(2),int(u*.10)); lw=max(s(1),int(u*.030)); alw=lw
    for yy in ys: d.line([xs[0],yy,xs[-1],yy],fill=TEAL,width=lw)
    for xx in xs:
        d.line([xx,ys[0]-h*.09,xx,ys[-1]+h*.05],fill=MAG,width=alw)
        arrow(d,xx,ys[-1]-h*.01,xx,ys[-1]+h*.05,MAG,alw,int(u*.10))
    mag=spec.get("mag",set()); boxes=spec.get("boxes",[])
    for r in range(rows):
        for c in range(cols):
            cx,cy=xs[c],ys[r]
            if (r,c) in mag: d.ellipse([cx-nr,cy-nr,cx+nr,cy+nr],fill=MAG)
            elif r==0: d.ellipse([cx-nr,cy-nr,cx+nr,cy+nr],fill=WHITE,outline=GRAY,width=lw)
            else: d.ellipse([cx-nr,cy-nr,cx+nr,cy+nr],fill=TEAL)
    cw_=w/cols; chh=h/rows
    for (r0,c0,r1,c1) in boxes:
        dashed(d,[x+c0*cw_+cw_*.10,y+r0*chh+chh*.10,x+(c1+1)*cw_-cw_*.10,y+(r1+1)*chh-chh*.10],DASH,max(s(1),int(u*.040)))
    if spec.get("diag"): arrow(d,xs[1],ys[0],xs[3],ys[1],MAG,alw,int(u*.12))
SPEC={"knit":{"mag":{(0,2)},"boxes":[(0,2,1,2)]},
      "tuck":{"mag":{(0,1),(0,2)},"boxes":[(0,1,0,2),(2,1,2,2)]},
      "miss":{"mag":{(1,2)},"boxes":[(0,2,0,2),(2,2,2,2)]},
      "xfer":{"mag":{(0,1),(1,3)},"boxes":[(0,0,0,1),(1,2,1,3)],"diag":True},
      "split":{"mag":{(0,2),(1,2)},"boxes":[(0,1,1,2)]},
      "carrier":{"mag":{(2,2)},"boxes":[(2,1,2,3)]}}
def panel_b(cxc,by,bw,bh,kind,u,wall):
    w=u*.48; ymid=by+bh/2; mw=max(s(2),int(u*.085))
    if kind=="knit":
        row_loops(d,cxc,ymid+u*.05,3,u,TEAL,wall)
        row_loops(d,cxc,ymid-u*.80,3,u,TEAL,wall)
        arrow(d,cxc,ymid-u*.70,cxc,ymid+u*.45,MAG,mw,int(u*.14))
    elif kind=="tuck":
        row_loops(d,cxc,ymid-u*.28,3,u,TEAL,wall)
        arch(d,cxc,ymid-u*1.02,w*.62,u*.72,MAG,wall,dot=False)
    elif kind=="miss":
        row_loops(d,cxc,ymid-u*.38,3,u,TEAL,wall)
        d.line([cxc-w*.95,ymid+u*.05,cxc+w*.95,ymid+u*.05],fill=MAG,width=int(mw*1.2))
    elif kind=="xfer":
        row_loops(d,cxc-w*.60,ymid-u*.38,1,u,TEAL,wall)
        row_loops(d,cxc+w*.95,ymid-u*.38,1,u,TEAL,wall)
        arch(d,cxc-w*.05,ymid-u*.62,w*.8,u*.95,MAG,wall,dot=False)
        arrow(d,cxc-w*.05,ymid-u*.85,cxc+w*.75,ymid-u*.42,MAG,mw,int(u*.14))
    elif kind=="split":
        row_loops(d,cxc,ymid-u*.42,3,u,TEAL,wall)
        d.line([cxc,ymid-u*.30,cxc+w*.62,ymid+u*.30],fill=MAG,width=mw)
        d.line([cxc,ymid-u*.30,cxc-w*.62,ymid+u*.30],fill=MAG,width=mw)
    elif kind=="carrier":
        row_loops(d,cxc-w*.95,ymid-u*.38,1,u,TEAL,wall)
        row_loops(d,cxc+w*.95,ymid-u*.38,1,u,TEAL,wall)
        d.line([cxc-w*.30,ymid-u*.80,cxc-w*.10,ymid+u*.20],fill=MAG,width=mw)
        d.line([cxc+w*.30,ymid-u*.80,cxc+w*.10,ymid+u*.20],fill=MAG,width=mw)
        arrow(d,cxc,ymid+u*.15,cxc,ymid+u*.62,MAG,mw,int(u*.14))
for idx,(key,title,abbr,cap) in enumerate(FAM):
    r,c=divmod(idx,3); x=m+c*(cw+gap); y=top0+r*(ch+gap)
    d.rounded_rectangle([x,y,x+cw,y+ch],radius=s(16),fill=CARD,outline=BORDER,width=s(2))
    d.text((x+s(26),y+s(16)),title,font=font(33,True),fill=NAVY)
    tw=d.textlength(title,font=font(33,True))
    d.text((x+s(26)+tw+s(12),y+s(30)),abbr,font=font(16,False,True),fill=GRAY)
    by=y+s(80); bh=ch-s(80)-s(66)
    pad=s(12); aw=cw*.30; bw=cw*.34; cwid=cw*.30
    axc=x+pad+aw/2; bxc=x+pad+aw+bw/2; cxc=x+pad+aw+bw+cwid/2
    u=aw*.52; wall=int(u*.075)
    row_loops(d,axc,by+bh/2-u/2,4,u,TEAL,wall)
    d.text((axc-s(7),by+bh*.82),"(a)",font=font(15),fill=NAVY)
    panel_b(bxc,by,bw,bh,key,u,wall)
    d.text((bxc-s(7),by+bh*.82),"(b)",font=font(15),fill=NAVY)
    lb=cwid*.94; lattice(cxc-lb/2, by+bh/2-lb/2, lb, lb, SPEC[key], u)
    d.text((cxc-s(7),by+bh*.82),"(c)",font=font(15),fill=NAVY)
    f=font(17); tw2=d.textlength(cap,font=f)
    d.text((x+cw/2-tw2/2,y+ch-s(42)),cap,font=f,fill=NAVY)
p=os.path.join(OUT,"actions_v2_preview.png"); img.save(p); print("written",p,img.size)
