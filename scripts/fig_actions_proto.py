import os, math
from PIL import Image, ImageDraw, ImageFont
ROOT = r"e:\DeskTop\knitting_pattern_generator"
OUT = os.path.join(ROOT, "outputs", "fig_actions_proto")
os.makedirs(OUT, exist_ok=True)
F = r"C:\Windows\Fonts"
SS = 2
def s(v): return v * SS
def font(sz, bold=False, ital=False):
    fn = "timesbd.ttf" if bold else ("timesi.ttf" if ital else "times.ttf")
    return ImageFont.truetype(os.path.join(F, fn), s(sz))
INK=(23,45,66); MUT=(82,103,122); EDGE=(203,213,225); GBG=(233,237,242); BG=(255,255,255)
C_KNIT=(255,0,16); C_TUCK=(0,164,255); C_MISS=(179,179,179); MISSED=(105,112,122)
C_XFER=(126,0,149); C_SPLIT=(214,180,0); C_CAR=(117,59,59)
FAM=[("knit","Knit","f_knit / b_knit",C_KNIT,"New loop is drawn through the loop below."),
     ("tuck","Tuck","f_tuck / b_tuck",C_TUCK,"Old loop retained; a new yarn is tucked."),
     ("miss","Miss","miss",C_MISS,"Needle not selected; no new loop formed."),
     ("xfer","Transfer","xfer_l1 / xfer_f_b",C_XFER,"A loop moves to an adjacent needle or bed."),
     ("split","Split","f_split / b_split",C_SPLIT,"A loop is divided for support / transition."),
     ("carrier","Drop-off","carrier",C_CAR,"Loop support removed at this wale (bind-off).")]
def cr(pts, seg=18):
    P=list(pts); out=[]
    for i in range(len(P)-1):
        p0=P[max(i-1,0)]; p1=P[i]; p2=P[i+1]; p3=P[min(i+2,len(P)-1)]
        for j in range(seg):
            t=j/seg; t2=t*t; t3=t2*t
            x=0.5*(2*p1[0]+(-p0[0]+p2[0])*t+(2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2+(-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
            y=0.5*(2*p1[1]+(-p0[1]+p2[1])*t+(2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2+(-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
            out.append((x,y))
    out.append(P[-1]); return out
def curve(d,pts,color,w): d.line(cr(pts),fill=color,width=w,joint="curve")
def loop(d,cx,ytop,depth,hw,color,w):
    pts=[(cx-hw,ytop-depth*0.28),(cx-hw,ytop+depth*0.7),(cx-hw*0.5,ytop+depth),(cx+hw*0.5,ytop+depth),(cx+hw,ytop+depth*0.7),(cx+hw,ytop-depth*0.28)]
    curve(d,pts,color,w)
def arrow(d,x1,y1,x2,y2,color,w,hs):
    d.line([x1,y1,x2,y2],fill=color,width=w)
    a=math.atan2(y2-y1,x2-x1)
    for t in (a+math.radians(150),a-math.radians(150)):
        d.line([x2,y2,x2+hs*math.cos(t),y2+hs*math.sin(t)],fill=color,width=w)
def wrap(d,txt,f,x,y,maxw,lh):
    words=txt.split(); line=""; yy=y
    for wd in words:
        t=(line+" "+wd).strip()
        if d.textlength(t,font=f)<=maxw: line=t
        else: d.text((x,yy),line,font=f,fill=MUT); line=wd; yy+=lh
    d.text((x,yy),line,font=f,fill=MUT)
W,H=s(1680),s(1240)
img=Image.new("RGB",(W,H),BG); d=ImageDraw.Draw(img)
d.text((s(26),s(10)),"Action primitives of the 15-class flat-knitting label space",font=font(27,True),fill=INK)
m=s(24); gap=s(20); top0=s(64)
cw=(W-2*m-2*gap)/3; ch=(H-top0-m-gap)/2
def panel_loops(lx,ly,lw,lh,kind):
    cols=5; rows=3; cellw=lw/cols; depth=lh*0.30; rowgap=lh*0.255; w=max(s(3),int(lh*0.022))
    ytop0=ly+lh*0.20
    for r in range(rows):
        ytop=ytop0+r*rowgap
        for c in range(cols):
            if kind=="miss" and r==0 and c==2: continue
            loop(d,lx+(c+0.5)*cellw,ytop,depth,cellw*0.40,INK,w)
        for c in range(cols-1):
            xa=lx+(c+0.5)*cellw+cellw*0.40; xb=lx+(c+1.5)*cellw-cellw*0.40
            d.line([xa,ytop,xb,ytop],fill=BG,width=max(s(2),w)); d.line([xa,ytop,xb,ytop],fill=INK,width=max(s(2),w-s(1)))
    cx=lx+2.5*cellw; ytop=ytop0; hw=cellw*0.40
    if kind=="knit": loop(d,cx,ytop,depth,hw,C_KNIT,w+s(3))
    elif kind=="tuck":
        loop(d,cx,ytop,depth,hw,C_TUCK,w+s(3)); loop(d,cx,ytop-depth*0.22,depth*0.60,hw*0.64,C_TUCK,w+s(1))
    elif kind=="miss":
        d.line([lx+2.0*cellw,ytop,lx+3.0*cellw,ytop],fill=MISSED,width=w+s(7))
        d.line([cx,ytop+2,cx,ytop+depth-2],fill=MISSED,width=max(s(2),w-s(1)))
    elif kind=="xfer":
        pts=[(cx-hw,ytop-depth*0.2),(cx-hw,ytop+depth*0.5),(cx-hw*0.1,ytop+depth),(cx+hw*1.5,ytop+depth),(cx+hw*1.9,ytop+depth*0.5),(cx+hw*1.9,ytop-depth*0.2)]
        curve(d,pts,C_XFER,w+s(3)); arrow(d,cx+hw*0.2,ytop-depth*0.5,cx+hw*1.9,ytop-depth*0.5,C_XFER,s(3),s(10))
    elif kind=="split":
        loop(d,cx,ytop,depth,hw,C_SPLIT,w+s(3)); curve(d,[(cx,ytop+depth),(cx+hw*0.9,ytop+depth*1.05),(cx+hw*1.6,ytop+depth*0.7)],C_SPLIT,w+s(1))
    elif kind=="carrier":
        curve(d,[(cx-hw,ytop-depth*0.2),(cx-hw,ytop+depth*0.6),(cx-hw*0.3,ytop+depth*0.95)],C_CAR,w+s(3))
        curve(d,[(cx+hw,ytop-depth*0.2),(cx+hw,ytop+depth*0.6),(cx+hw*0.3,ytop+depth*0.95)],C_CAR,w+s(3))
        arrow(d,cx,ytop+depth*0.7,cx,ytop+depth*1.35,C_CAR,s(3),s(9))
def panel_grid(gx,gy,gs,kind):
    col=dict(knit=C_KNIT,tuck=C_TUCK,miss=C_MISS,xfer=C_XFER,split=C_SPLIT,carrier=C_CAR)[kind]
    n=5; cs=gs/n
    motif=dict(knit=[(r,2) for r in range(5)],tuck=[(1,1),(2,1),(1,3),(2,3)],
               miss=[(1,1),(1,2),(1,3),(2,1),(2,3),(3,1),(3,2),(3,3)],
               xfer=[(1,1),(2,2),(3,3)],split=[(1,2),(2,2),(3,2),(1,1)],carrier=[(4,c) for c in range(5)])
    for r in range(n):
        for c in range(n):
            x=gx+c*cs; y=gy+r*cs; d.rectangle([x,y,x+cs,y+cs],fill=GBG,outline=BG,width=s(2))
    for (r,c) in motif[kind]:
        x=gx+c*cs; y=gy+r*cs; d.rectangle([x,y,x+cs,y+cs],fill=col,outline=BG,width=s(2))
    if kind=="miss": d.rectangle([gx+2*cs+cs*0.28,gy+2*cs+cs*0.28,gx+3*cs-cs*0.28,gy+3*cs-cs*0.28],fill=BG,outline=C_MISS,width=s(2))
    if kind=="xfer": arrow(d,gx+1.5*cs,gy+1.5*cs,gx+3.5*cs,gy+3.5*cs,C_XFER,s(2),s(7))
    d.rectangle([gx,gy,gx+gs,gy+gs],outline=EDGE,width=s(2))
for idx,(key,title,abbr,col,cap) in enumerate(FAM):
    r,c=divmod(idx,3); x=m+c*(cw+gap); y=top0+r*(ch+gap)
    d.rounded_rectangle([x,y,x+cw,y+ch],radius=s(14),fill=BG,outline=EDGE,width=s(2))
    d.text((x+s(16),y+s(12)),title,font=font(30,True),fill=INK)
    d.text((x+s(18),y+s(50)),abbr,font=font(17,False,True),fill=MUT)
    d.rounded_rectangle([x+cw-s(58),y+s(18),x+cw-s(16),y+s(42)],radius=s(6),fill=col,outline=EDGE,width=s(1))
    cy0=y+s(70); cy1=y+ch-s(46)
    lw=cw*0.57; panel_loops(x+s(16),cy0,lw,cy1-cy0,key)
    gs=cw*0.33; panel_grid(x+cw-s(14)-gs, cy0+((cy1-cy0)-gs)/2, gs, key)
    wrap(d,cap,font(16),x+s(16),y+ch-s(38),cw-s(32),s(20))
p=os.path.join(OUT,"actions_embed.png"); img.save(p)
print("written",p,img.size,"dpi~",round(img.size[0]/(160/25.4)))
