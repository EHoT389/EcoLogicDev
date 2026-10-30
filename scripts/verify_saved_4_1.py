"""Verify the explicitly isolated browser QA project and its bilingual reports."""
from pathlib import Path
from io import BytesIO
import json
import sqlite3
import httpx
from pypdf import PdfReader
from openpyxl import load_workbook
import pypdfium2 as pdfium

folder=Path('output/qa')
with sqlite3.connect(folder/'e2e-4-1.db') as db:
    email=db.execute('SELECT email FROM users WHERE name=?',('EcoLogic QA 4.1',)).fetchone()[0]
with httpx.Client(base_url='http://127.0.0.1:8001/api',timeout=40) as client:
    login=client.post('/auth/login',json={'email':email,'password':'EcoLogic-QA-41-2026!'})
    login.raise_for_status()
    projects=client.get('/projects').json()
    project=next(p for p in projects if p['name']=='QA 4.1 — RU — map restore')
    data=client.get('/projects/'+project['id']).json()
    cost=data['result']['estimate']['total']
    for lang in ('ru','kk'):
        for kind in ('pdf','xlsx'):
            response=client.get('/reports/'+project['id']+'/'+kind,headers={'Accept-Language':lang})
            response.raise_for_status();path=folder/f'4-1-project-{lang}.{kind}';path.write_bytes(response.content)
            if kind=='pdf':
                pages=PdfReader(BytesIO(response.content)).pages
                assert str(cost) in '\n'.join(page.extract_text() for page in pages)
                document=pdfium.PdfDocument(response.content)
                for index in range(len(document)):
                    page=document[index];bitmap=page.render(scale=1.25)
                    bitmap.to_pil().save(folder/f'4-1-project-{lang}-page-{index+1}.png')
                    bitmap.close();page.close()
                document.close()
            else:
                book=load_workbook(BytesIO(response.content))
                assert book.worksheets[0].cell(book.worksheets[0].max_row,5).value==cost
    print(json.dumps({'status':'passed','project_cost':cost,'plants':data['result']['total_plants'],
                      'map_state_restored':bool(data['map_state']),'languages':['ru','kk'],'reports':['pdf','xlsx']}))
