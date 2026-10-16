import os, math
from PIL import Image, ImageDraw, ImageFont
ROOT=r"e:\DeskTop\knitting_pattern_generator"; OUT=os.path.join(ROOT,"outputs","fig_actions_proto")
os.makedirs(OUT,exist_ok=True); F=r"C:\Windows\Fonts"; SS=1
def s(v): return v*SS
def font(sz,bold=False,ital=False):
    fn="timesbd.ttf" if bold else ("timesi.ttf" if ital else "times.ttf")
    return ImageFont.truetype(os.path.join(F,fn),s(sz))
PAGE=(232,241,250); CARD=(255,255,255); BORDER=(213,227,242); NAVY=(31,56,100)
TEAL=(45,166,166); MAG=(230,0,126); GRAY=(150,158,168); WHITE=(255,255,255); DASH=(45,45,45)
FAM=[("knit","Knit","f_knit / b_knit","New loop is drawn through the loop below."),
     ("tuck","Tuck","f_tuck / b_tuck","Old loop retained; a new yarn is tucked."),
     ("miss","Miss","miss","Needle not selected; no new loop formed."),
     ("xfer","Transfer","xfer_l1 / xfer_f_b","A loop moves to an adjacent needle or bed."),
     ("split","Split","f_split / b_split","A loop is divided for support / transition."),
     ("carrier","Drop-off","carrier","Loop support removed at this wale (bind-off).")]
def cr(pts,seg=16):
    P=list(pts); out=[]
    for i in range(len(P)-1):
        p0=P[max(i-1,0)];p1=P[i];p2=P[i+1];p3=P[min(i+2,len(P)-1)]
        for j in range(seg):
            t=j/seg;t2=t*t;t3=t2*t
            x=.5*(2*p1[0]+(-p0[0]+p2[0])*t+(2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2+(-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
            y=.5*(2*p1[1]+(-p0[1]+p2[1])*t+(2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2+(-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
            out.append((x,y))
    out.append(P[-1]);return out
def curve(d,pts,color,w): d.line(cr(pts),fill=color,width=w,joint="curve")
def arch(d,cx,ytop,w,h,color,lw,dot=True):
    hf=w/2
    pts=[(cx-hf,ytop+h),(cx-hf,ytop+h*.5),(cx-hf*.72,ytop+h*.10),(cx,ytop),
         (cx+hf*.72,ytop+h*.10),(cx+hf,ytop+h*.5),(cx+hf,ytop+h)]
    curve(d,pts,color,lw)
    if dot:
        r=lw*.42; d.ellipse([cx-r,ytop+lw*.55-r,cx+r,ytop+lw*.55+r],fill=WHITE)
def course(d,xl,ytop,n,w,h,color,lw,ov=.24):
    step=w*(1-ov)
    for i in range(n): arch(d,xl+i*step+w/2,ytop,w,h,color,lw)
def arrow(d,x1,y1,x2,y2,color,w,hs):
    d.line([x1,y1,x2,y2],fill=color,width=w)
    a=math.atan2(y2-y1,x2-x1)
    for t in (a+math.radians(150),a-math.radians(150)):
        d.line([x2,y2,x2+hs*math.cos(t),y2+hs*math.sin(t)],fill=color,width=w)
def dashed(d,box,color,w,dlen=6):
    x0,y0,x1,y1=box
    for (ax,ay,bx,by) in [(x0,y0,x1,y0),(x1,y0,x1,y1),(x1,y1,x0,y1),(x0,y1,x0,y0)]:
        L=math.hypot(bx-ax,by-ay); n=max(1,int(L/dlen))
        for k in range(0,n,2):
            t0=k/n; t1=min(1,(k+1)/n)
            d.line([ax+(bx-ax)*t0,ay+(by-ay)*t0,ax+(bx-ax)*t1,ay+(by-ay)*t1],fill=color,width=w)
W,H=s(1800),s(1240)
img=Image.new("RGB",(W,H),PAGE); d=ImageDraw.Draw(img)
m=s(26); gap=s(22); top0=s(20)
cw=(W-2*m-2*gap)/3; ch=(H-top0-m-gap)/2
def lattice(x,y,w,h,spec):
    rows,cols=3,5
    xs=[x+w*(c+.5)/cols for c in range(cols)]
    ys=[y+h*(r+.5)/rows for r in range(rows)]
    nr=max(s(3),int(min(w,h)*.045)); lw=max(s(1),int(h*.012))
    for yy in ys: d.line([xs[0],yy,xs[-1],yy],fill=TEAL,width=lw)
    for xx in xs:
        d.line([xx,ys[0]-h*.10,xx,ys[-1]+h*.06],fill=MAG,width=lw)
        arrow(d,xx,ys[-1]-h*.02,xx,ys[-1]+h*.06,MAG,lw,s(5))
    mag=spec.get("mag",set()); boxes=spec.get("boxes",[])
    for r in range(rows):
        for c in range(cols):
            cx,cy=xs[c],ys[r]
            if (r,c) in mag: d.ellipse([cx-nr,cy-nr,cx+nr,cy+nr],fill=MAG)
            elif r==0: d.ellipse([cx-nr,cy-nr,cx+nr,cy+nr],fill=WHITE,outline=GRAY,width=lw)
            else: d.ellipse([cx-nr,cy-nr,cx+nr,cy+nr],fill=TEAL)
    cw_=w/cols; chh=h/rows
    for (r0,c0,r1,c1) in boxes:
        dashed(d,[x+c0*cw_+cw_*.08,y+r0*chh+chh*.08,x+(c1+1)*cw_-cw_*.08,y+(r1+1)*chh-chh*.08],DASH,max(s(1),int(h*.014)))
    if spec.get("diag"):
        arrow(d,xs[1],ys[0],xs[3],ys[1],MAG,lw,s(6))
SPEC={"knit":{"mag":{(0,2)},"boxes":[(0,2,1,2)]},
      "tuck":{"mag":{(0,1),(0,2)},"boxes":[(0,1,0,2),(2,1,2,2)]},
      "miss":{"mag":{(1,2)},"boxes":[(0,2,0,2),(2,2,2,2)]},
      "xfer":{"mag":{(0,1),(1,3)},"boxes":[(0,0,0,1),(1,2,1,3)],"diag":True},
      "split":{"mag":{(0,2),(1,2)},"boxes":[(0,1,1,2)]},
      "carrier":{"mag":{(2,2)},"boxes":[(2,1,2,3)]}}
def panel_b(x,y,w,h,kind):
    lw=max(s(4),int(h*.055)); lw2=lw
    n=3; ww=w*.42; hh=h*.52
    if kind=="knit":
        course(d,x+w*.06,y+h*.44,n,ww,hh,TEAL,lw)
        course(d,x+w*.06,y+h*.02,n,ww,hh,TEAL,lw)
    elif kind=="tuck":
        course(d,x+w*.06,y+h*.30,n,ww,hh,TEAL,lw)
        cx=x+w*.06+ww*(1-.24)+ww/2
        d.line([cx-ww*.16,y+h*.10,cx-ww*.16,y+h*.40],fill=MAG,width=lw)
        d.line([cx+ww*.16,y+h*.10,cx+ww*.16,y+h*.40],fill=MAG,width=lw)
        arch(d,cx,y+h*.02,ww*.5,hh*.4,MAG,max(s(3),lw- s(1)),dot=False)
    elif kind=="miss":
        arch(d,x+w*.16,y+h*.30,ww,hh,TEAL,lw)
        arch(d,x+w*.16+ww*.76*2,y+h*.30,ww,hh,TEAL,lw)
        d.line([x+w*.16+ww*.4,y+h*.52,x+w*.16+ww*.76*2+ww*.6,y+h*.52],fill=MAG,width=int(lw*1.3))
    elif kind=="xfer":
        arch(d,x+w*.10,y+h*.30,ww,hh,TEAL,lw)
        arch(d,x+w*.10+ww*.76*2,y+h*.30,ww,hh,TEAL,lw)
        cx=x+w*.10+ww*.76
        pts=[(cx-ww*.3,y+h*.55),(cx-ww*.1,y+h*.20),(cx+ww*.35,y+h*.05),(cx+ww*.6,y+h*.30)]
        curve(d,pts,MAG,lw)
        arrow(d,cx-ww*.1,y+h*.12,cx+ww*.7,y+h*.30,MAG,max(s(3),lw-s(1)),s(8))
    elif kind=="split":
        course(d,x+w*.06,y+h*.30,n,ww,hh,TEAL,lw)
        cx=x+w*.06+ww*(1-.24)+ww/2
        curve(d,[(cx,y+h*.34),(cx+ww*.4,y+h*.42),(cx+ww*.7,y+h*.62)],MAG,max(s(3),lw-s(1)))
        curve(d,[(cx,y+h*.34),(cx-ww*.4,y+h*.42),(cx-ww*.7,y+h*.62)],MAG,max(s(3),lw-s(1)))
    elif kind=="carrier":
        arch(d,x+w*.10,y+h*.30,ww,hh,TEAL,lw)
        arch(d,x+w*.10+ww*.76*2,y+h*.30,ww,hh,TEAL,lw)
        cx=x+w*.10+ww*.76
        curve(d,[(cx-ww*.3,y+h*.10),(cx-ww*.3,y+h*.40),(cx-ww*.1,y+h*.60)],MAG,lw)
        curve(d,[(cx+ww*.3,y+h*.10),(cx+ww*.3,y+h*.40),(cx+ww*.1,y+h*.60)],MAG,lw)
        arrow(d,cx,y+h*.55,cx,y+h*.85,MAG,max(s(3),lw-s(1)),s(8))
for idx,(key,title,abbr,cap) in enumerate(FAM):
    r,c=divmod(idx,3); x=m+c*(cw+gap); y=top0+r*(ch+gap)
    d.rounded_rectangle([x,y,x+cw,y+ch],radius=s(16),fill=CARD,outline=BORDER,width=s(2))
    d.text((x+s(26),y+s(18)),title,font=font(34,True),fill=NAVY)
    tw=d.textlength(title,font=font(34,True))
    d.text((x+s(26)+tw+s(14),y+s(30)),abbr,font=font(17,False,True),fill=GRAY)
    band_y=y+s(86); band_h=ch-s(86)-s(74)
    pa_w=cw*.30; pb_w=cw*.32; pc_w=cw*.30
    ax=x+s(20); bx=ax+pa_w+s(6); cxp=bx+pb_w+s(6)
    course(d,ax+s(4),band_y+band_h*.30,4,pa_w*.40,band_h*.50,TEAL,max(s(4),int(band_h*.06)))
    d.text((ax+pa_w*.5-s(6),band_y+band_h+s(4)),"(a)",font=font(15),fill=NAVY)
    panel_b(bx,band_y,pb_w,band_h,key)
    d.text((bx+pb_w*.5-s(6),band_y+band_h+s(4)),"(b)",font=font(15),fill=NAVY)
    lattice(cxp,band_y,pc_w,band_h,SPEC[key])
    d.text((cxp+pc_w*.5-s(6),band_y+band_h+s(4)),"(c)",font=font(15),fill=NAVY)
    f=font(17); tw2=d.textlength(cap,font=f)
    d.text((x+cw/2-tw2/2,y+ch-s(44)),cap,font=f,fill=NAVY)
p=os.path.join(OUT,"actions_v2_preview.png"); img.save(p); print("written",p,img.size)
