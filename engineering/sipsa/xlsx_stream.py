"""Streaming XLSX reader for source auditing (no workbook writes).
Keeps raw strings/identifiers and source row numbers; dates parsed by caller.
"""
from zipfile import ZipFile
from lxml import etree as E
from pathlib import PurePosixPath
import posixpath
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
N={'m':NS}
class Xlsx:
 def __init__(self,path):
  self.z=ZipFile(path); self.ss=[]
  if 'xl/sharedStrings.xml' in self.z.namelist():
   for _,el in E.iterparse(self.z.open('xl/sharedStrings.xml'),events=('end',),tag='{'+NS+'}si'):
    self.ss.append(''.join(t.text or '' for t in el.iter('{'+NS+'}t')))
    el.clear()
    while el.getprevious() is not None: del el.getparent()[0]
  rels={el.get('Id'):el.get('Target') for el in E.fromstring(self.z.read('xl/_rels/workbook.xml.rels'))}
  wb=E.fromstring(self.z.read('xl/workbook.xml'))
  prop=wb.find('m:workbookPr',N)
  assert prop is None or prop.get('date1904') not in ('1','true'),'Unsupported 1904 dates'
  self.sheets=[]
  for s in wb.findall('m:sheets/m:sheet',N):
   t=rels[s.get('{'+REL+'}id')]
   target=t.lstrip('/') if t.startswith('/') else posixpath.normpath('xl/'+t)
   self.sheets.append((s.get('name'),target))
 def rows(self,target):
  for _,el in E.iterparse(self.z.open(target),events=('end',),tag='{'+NS+'}row'):
   vals={}
   for c in el:
    ref=c.get('r',''); col=ref.rstrip('0123456789')
    v=c.find('{'+NS+'}v'); text=v.text if v is not None else None
    if c.get('t')=='s' and text is not None: value=self.ss[int(text)]
    elif c.get('t')=='inlineStr': value=''.join(t.text or '' for t in c.iter('{'+NS+'}t'))
    elif text is not None: value=text
    else: continue
    vals[col]=value
   row=int(el.get('r')); el.clear()
   while el.getprevious() is not None: del el.getparent()[0]
   yield row,vals
 def close(self): self.z.close()
