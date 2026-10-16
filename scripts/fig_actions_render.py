import os, time
import pythoncom, win32com.client
from PIL import Image
ROOT=r"e:\DeskTop\knitting_pattern_generator"
STEM=os.path.join(ROOT,"docs","figures","Fig_Actions_Primitives_EN")
PPTX=STEM+".pptx"; PNG=STEM+".png"; PDF=STEM+".pdf"
pythoncom.CoInitialize()
app=None; pres=None
try:
    try: app=win32com.client.GetActiveObject('PowerPoint.Application')
    except Exception: app=win32com.client.Dispatch('PowerPoint.Application')
    for a in range(12):
        try:
            pres=app.Presentations.Open(PPTX, True, False, False); break
        except Exception:
            if a==11: raise
            time.sleep(1)
    W=pres.PageSetup.SlideWidth; H=pres.PageSetup.SlideHeight
    pxw=3200; pxh=round(pxw*H/W)
    slide=pres.Slides.Item(1)
    slide.Export(PNG,'PNG',pxw,pxh)
    pres.SaveAs(PDF,32)
    print("rendered",PNG,Image.open(PNG).size,"pdf",os.path.exists(PDF))
finally:
    if pres is not None:
        try: pres.Close()
        except Exception: pass
    pythoncom.CoUninitialize()
