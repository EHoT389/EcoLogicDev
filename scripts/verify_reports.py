"""Produce one deterministic QA report without user data."""
from pathlib import Path
import sys
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.analytics import analyze
from backend.schemas import AnalysisInput
from backend.data import ZONES
from backend.reports import export_pdf,export_xlsx
result=analyze(AnalysisInput(geometry=ZONES[1]['geometry']).model_dump())
project=SimpleNamespace(name='Павлодар - демонстрационный план озеленения',updated='2026-10-28T00:00:00Z',result=result)
folder=Path('output/qa');folder.mkdir(parents=True,exist_ok=True)
(folder/'demo-report.pdf').write_bytes(export_pdf(project))
(folder/'demo-report.xlsx').write_bytes(export_xlsx(project))
from pypdf import PdfReader
pdf=PdfReader(folder/'demo-report.pdf');print('PDF pages:',len(pdf.pages),'Cyrillic:',all('EcoLogicDev' in p.extract_text() for p in pdf.pages))
from openpyxl import load_workbook
wb=load_workbook(folder/'demo-report.xlsx');print('Excel sheets:',wb.sheetnames)
try:
 import pypdfium2 as pdfium
 doc=pdfium.PdfDocument(str(folder/'demo-report.pdf'))
 for i,page in enumerate(doc): page.render(scale=1.4).to_pil().save(folder/f'pdf-page-{i+1}.png')
 print('Rendered pages using bundled PDFium (Poppler executable unavailable).')
except ImportError:
 print('PDF renderer unavailable; review PDF in viewer.')
