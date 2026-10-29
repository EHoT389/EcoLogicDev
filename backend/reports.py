from .localization import text
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def export_xlsx(project, lang='ru'):
    t = lambda value: text(value, lang)
    wb = Workbook()
    ws = wb.active
    ws.title = t('Смета')
    ws.append(['EcoLogicDev', project.name])
    ws.append([t('Дата'), project.updated])
    ws.append([t('Версия'), project.result['version']])
    ws.append([t('Статья'), t('Количество'), t('Единица'), t('Цена, ₸'), t('Итого, ₸')])
    for r in project.result['estimate']['rows']:
        ws.append([r['kk'] if lang == 'kk' else r['ru'], r['quantity'], t(r['unit']), r['price'], r['total']])
    ws.append([t('Итого'), '', '', '', project.result['estimate']['total']])
    eco = wb.create_sheet(t('Экология'))
    eco.append([t('Горизонт, лет'), t('CO₂, кг/год'), t('CO₂ накоплено, кг'), t('O₂, кг/год'), t('Кроны, м²')])
    for r in project.result['ecology']:
        eco.append([r['year'], r['co2'], r['cumulative_co2'], r['oxygen'], r['canopy']])
    sources = wb.create_sheet(t('Источники'))
    sources.append([t('Оценочные данные'), t('Экспертная модель, не полевые измерения')])
    sources.append([t('Расценки'), t(project.result['rate_snapshot']['source'])])
    sources.append(['CO₂', 'https://research.fs.usda.gov/treesearch/46254'])
    sources.append([t('Прайсы'), 'https://www.greenmax.kz/index.php/price'])
    sources.append([t('Коэффициенты'), str({**project.result['coefficient_snapshot'], 'source': t(project.result['coefficient_snapshot'].get('source',''))})])
    sources.append([t('Ограничения'), t('Демонстрационные характеристики участка. Температурный эффект не рассчитан.')])
    for sheet in wb:
        sheet.freeze_panes = 'A2'
        for cell in sheet[1]:
            cell.font = Font(color='FFFFFF', bold=True)
            cell.fill = PatternFill('solid', fgColor='174D3D')
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = min(65, max(18, max((len(str(c.value or '')) for c in col)) + 2))
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith(('=', '+', '-', '@')):
                    cell.value = "'" + cell.value
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

def export_pdf(project, lang='ru'):
    t = lambda value: text(value, lang)
    paths = [Path(__file__).parent / 'assets' / 'DejaVuSans.ttf', Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'), Path('C:/Windows/Fonts/arial.ttf')]
    font = next((p for p in paths if p.exists()), None)
    if font is None:
        raise RuntimeError(t('Установите DejaVu Sans для кириллицы PDF'))
    if 'EcoFont' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('EcoFont', str(font)))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Eco', fontName='EcoFont', fontSize=10, leading=15, spaceAfter=8))
    styles.add(ParagraphStyle(name='EcoTitle', fontName='EcoFont', fontSize=22, leading=28, spaceAfter=16))
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = [Paragraph('EcoLogicDev', styles['EcoTitle']), Paragraph(escape(project.name), styles['EcoTitle']), Paragraph(t('Расчёт от ') + escape(project.updated[:10]) + t(' · версия ') + project.result['version'], styles['Eco']), Paragraph(t('Предварительная экспертная оценка. Характеристики участка могут быть демонстрационными; показатели не являются полевыми измерениями.'), styles['Eco'])]
    data = [[Paragraph(t, styles['Eco']) for t in [t('Статья'), t('Объём'), t('Итого, ₸')]]]
    for r in project.result['estimate']['rows']:
        data.append([Paragraph(escape(r['kk'] if lang == 'kk' else r['ru']), styles['Eco']), Paragraph(str(r['quantity']) + ' ' + t(r['unit']), styles['Eco']), Paragraph(f"{r['total']:,.0f}".replace(',', ' '), styles['Eco'])])
    table = Table(data, colWidths=[260, 110, 125], repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e7f0e8')), ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#d4ded5')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
    story.append(table)
    story.append(Spacer(1, 15))
    story.append(Paragraph(t('Итого: ') + str(project.result['estimate']['total']) + ' ₸', styles['EcoTitle']))
    for r in project.result['ecology']:
        story.append(Paragraph(f"{r['year']}{t(' лет: CO2 ')}{r['co2']}{t(' кг/год; накоплено ')}{r['cumulative_co2']}{t(' кг; оценка крон ')}{r['canopy']}{t(' м².')}", styles['Eco']))
    for w in project.result['warnings']:
        story.append(Paragraph(escape(t(w)), styles['Eco']))
    story.append(PageBreak())
    story.append(Paragraph(t('Состав посадок и методика'), styles['EcoTitle']))
    plants = [[Paragraph(t, styles['Eco']) for t in [t('Вид'), t('Количество'), t('Шаг, м'), t('3-й год, %')]]]
    for item in project.result['plan']:
        plants.append([Paragraph(escape(item['kk'] if lang == 'kk' else item['ru']), styles['Eco']), str(item['count']), str(item['spacing']), str(item['survival'][2])])
    plant_table = Table(plants, colWidths=[245, 85, 80, 85], repeatRows=1)
    plant_table.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), 'EcoFont'), ('FONTSIZE', (0, 0), (-1, -1), 10), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e7f0e8')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
    story.extend([plant_table, Spacer(1, 22), Paragraph(t('Источники и допущения'), styles['EcoTitle'])])
    coeff = project.result['coefficient_snapshot']
    for line in [t('Цены саженцев: https://www.greenmax.kz/index.php/price; https://plants.kz/posadochnyj-material. Получено 28.10.2026. Размеры посадочного материала указаны в каталоге.'), t('CO2: Nowak et al. 2013, https://research.fs.usda.gov/treesearch/46254. 0,28 кг C/м² крон/год, перенос оценки США без калибровки по Павлодару.'), t('Приживаемость, рост крон, пыль и перехват осадков: экспертные допущения, низкая уверенность. Температурный эффект: недостаточно данных.'), t(project.result['rate_snapshot']['source']), f"{t('Версия коэффициентов: ')}{coeff['version']}{t('. Срок роста кроны: ')}{coeff['growth_years']}{t(' лет. Базовое сохранение: ')}{coeff['survival_base'] * 100:.0f}{t('% в год.')}", t(project.result['placement_status'])]:
        story.append(Paragraph(escape(line), styles['Eco']))

    def footer(c, doc):
        c.setFont('EcoFont', 8)
        c.drawString(40, 24, t('EcoLogicDev · Оценочный отчёт'))
        c.drawRightString(555, 24, str(doc.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
