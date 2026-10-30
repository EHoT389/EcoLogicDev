"""Inspect actual city/zone report exports; never create analytical satellite data."""
from io import BytesIO
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pypdf import PdfReader
from openpyxl import load_workbook
from backend.monitoring import service, reports
from backend.data import ZONES


def main():
    metadata = service.metadata()
    assert metadata['status'] == 'ready' and metadata['scope'] == 'administrative_city'
    folder = Path('output/qa/city-reports')
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for scope, zone_id in (('city', None), ('zone', ZONES[0]['id'])):
        image = service.change_map_png(zone_id)
        for language in ('ru', 'kk'):
            result = service.get_vegetation_change(zone_id, language=language)
            stem = f'{scope}-{language}'
            pdf = reports.export_pdf(result, image, language)
            excel = reports.export_xlsx(result, image, language)
            (folder / f'{stem}.pdf').write_bytes(pdf)
            (folder / f'{stem}.xlsx').write_bytes(excel)
            reader = PdfReader(BytesIO(pdf))
            workbook = load_workbook(BytesIO(excel))
            assert workbook.worksheets[0]['B5'].value == round(result['statistics']['vegetation_2020_ha'], 4)
            text = '\n'.join(page.extract_text() for page in reader.pages)
            assert all(scene['id'] in text for period in result['periods'].values() for scene in period['scenes'])
            record = {'scope': scope, 'language': language, 'pdf_bytes': len(pdf), 'xlsx_bytes': len(excel),
                      'pages': len(reader.pages), 'dataset_id': result['dataset_id']}
            try:
                import pypdfium2 as pdfium
            except ImportError:
                record['rendering'] = 'unavailable: install optional pypdfium2'
            else:
                document = pdfium.PdfDocument(pdf)
                for index in range(len(document)):
                    document[index].render(scale=1.2).to_pil().save(folder / f'{stem}-page-{index+1}.png')
                record['rendering'] = 'all pages rendered'
            records.append(record)
    (folder / 'verification.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(json.dumps(records, indent=2))


if __name__ == '__main__':
    main()
