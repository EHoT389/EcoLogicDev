"""Satellite reports: actual validated server results and rendered change raster only."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from PIL import Image as PILImage,ImageDraw
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.chart import BarChart,Reference

LABELS=[
 ('vegetation_2020_ha','Растительность 2020, га','Өсімдік жамылғысы 2020, га'),
 ('vegetation_2026_ha','Растительность 2026, га','Өсімдік жамылғысы 2026, га'),
 ('gain_ha','Прирост, га','Өсім, га'),('loss_ha','Потери, га','Жоғалу, га'),
 ('net_change_ha','Чистое изменение, га','Таза өзгеріс, га'),('change_percent','Изменение к 2020, %','2020 жылға қатысты өзгеріс, %'),
 ('mean_ndvi_2020','Средний NDVI 2020','Орташа NDVI 2020'),('mean_ndvi_2026','Средний NDVI 2026','Орташа NDVI 2026'),
 ('comparable_fraction','Доля пригодных пикселей, %','Жарамды пиксельдер үлесі, %'),
 ('scope_area_ha','Площадь сетки анализа, га','Талдау торының ауданы, га'),
 ('aoi_coverage_fraction','Покрытие выбранной территории, %','Таңдалған аумақты қамту, %')]

def t(ru,kk,language): return kk if language=='kk' else ru
def _value(key,value):
 if value is None:return '—'
 if key in ('comparable_fraction','aoi_coverage_fraction'): value*=100
 return round(value,4)
def _safe(value):
 if isinstance(value,str) and value.startswith(('=','+','-','@')): return "'"+value
 return value
def _font():
 if 'EcoMonitor' not in pdfmetrics.getRegisteredFontNames():
  paths=[Path(__file__).resolve().parents[1]/'assets'/'DejaVuSans.ttf',Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('C:/Windows/Fonts/arial.ttf')]
  font=next((p for p in paths if p.exists()),None)
  if font is None: raise RuntimeError('Cyrillic PDF font unavailable')
  pdfmetrics.registerFont(TTFont('EcoMonitor',str(font)))
 return 'EcoMonitor'
def _scenes(result):
 for year,period in result['periods'].items():
  for scene in period.get('scenes',[]): yield year,scene

def ndvi_chart(result,language):
 # A two-period chart of the two measured seasonal means, without interpolated years.
 image=PILImage.new('RGB',(1000,240),'white');draw=ImageDraw.Draw(image)
 draw.line((90,120,950,120),fill='#a9b3aa',width=2)
 for i,year in enumerate((2020,2026)):
  value=result['statistics'][f'mean_ndvi_{year}'];x=250+500*i
  if value is not None:
   y=120-int(value*95);draw.rectangle((x-70,min(y,120),x+70,max(y,120)),fill='#477d56')
   draw.text((x-36,max(4,y-23)),f'{value:.4f}',fill='#264932')
  draw.text((x-20,218),str(year),fill='#264932')
 buffer=BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()

def export_pdf(result,map_png,language='ru'):
 font=_font();normal=ParagraphStyle('MonitorBody',fontName=font,fontSize=9,leading=13,spaceAfter=7)
 title=ParagraphStyle('MonitorTitle',fontName=font,fontSize=20,leading=26,spaceAfter=14)
 heading=ParagraphStyle('MonitorHeading',fontName=font,fontSize=13,leading=18,spaceAfter=10)
 name=result['territory']['kk' if language=='kk' else 'ru']
 output=BytesIO();doc=SimpleDocTemplate(output,leftMargin=40,rightMargin=40,topMargin=35,bottomMargin=38)
 story=[Paragraph('EcoLogicDev · 2020–2026',title),Paragraph(escape(name),heading),Paragraph(t('Мониторинг вероятного растительного покрова · Sentinel-2 L2A','Ықтимал өсімдік жамылғысының мониторингі · Sentinel-2 L2A',language),normal),Paragraph(t('Периоды: 1 июня — 31 августа обоих лет. Все площади относятся к общей маске пригодных пикселей.','Кезеңдер: екі жылда да 1 маусым — 31 тамыз. Барлық аудандар жарамды пиксельдердің ортақ маскасына қатысты.',language),normal)]
 rows=[[t('Показатель','Көрсеткіш',language),t('Значение','Мәні',language)]]
 for key,ru,kk in LABELS:rows.append([Paragraph(kk if language=='kk' else ru,normal),str(_value(key,result['statistics'].get(key)))])
 table=Table(rows,colWidths=[365,130],repeatRows=1)
 table.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),font),('FONTSIZE',(0,0),(-1,-1),9),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7f0e8')),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#d4ded5')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),5)]));story.extend([table,Spacer(1,10)])
 for w in result['warnings'][:4]:story.append(Paragraph(escape(w),normal))
 story.extend([PageBreak(),Paragraph(t('Карта изменений','Өзгерістер картасы',language),title)])
 image=PILImage.open(BytesIO(map_png));ratio=min(495/image.width,300/image.height)
 story.append(Image(BytesIO(map_png),width=image.width*ratio,height=image.height*ratio))
 story.append(Paragraph(t('Зелёный — вероятный прирост; красный — потеря; серый — без смены класса; прозрачный — нет достоверных данных.','Жасыл — ықтимал өсім; қызыл — жоғалу; сұр — класс өзгермеген; мөлдір — сенімді дерек жоқ.',language),normal))
 story.append(Paragraph(t('Средний сезонный NDVI','Орташа маусымдық NDVI',language),heading));story.append(Image(BytesIO(ndvi_chart(result,language)),width=495,height=119))
 story.append(Paragraph(t('NDVI = (B08 − B04) / (B08 + B04). Порог растительности: ','NDVI = (B08 − B04) / (B08 + B04). Өсімдік шегі: ',language)+str(result['threshold']),normal))
 story.append(PageBreak());story.append(Paragraph(t('Методика и источники','Әдістеме мен дереккөздер',language),title))
 story.append(Paragraph(t('Медиана нескольких снимков каждого летнего периода. Сетка EPSG:32643, 10 м; SCL допускает 4/5/6. Не менее двух наблюдений каждого года на сравниваемый пиксель. Площади: число пикселей × 100 м².','Әр жазғы кезеңдегі бірнеше суреттің медианасы. EPSG:32643 торы, 10 м; SCL 4/5/6 кластарын өткізеді. Салыстырылатын пиксельде әр жылға кемінде екі бақылау. Аудандар: пиксель саны × 100 м².',language),normal))
 story.append(Paragraph(escape(result['source']['attribution']),normal))
 story.append(Paragraph(escape(result['source']['catalog']),normal))
 story.append(Paragraph('Dataset: '+escape(str(result.get('dataset_id'))),normal))
 for year,scene in _scenes(result):
  line=f"{year} · {scene['id']} · {scene.get('date',scene.get('datetime',''))} · "+t('облачность сцены: ','суреттің бұлттылығы: ',language)+str(scene.get('cloud_cover','—'))+'%'
  story.append(Paragraph(escape(line),normal));story.append(Paragraph(escape(scene.get('source',result['source']['catalog'])),normal))
 def footer(c,document):
  c.setFont(font,8);c.drawString(40,20,'EcoLogicDev · Sentinel-2 L2A');c.drawRightString(555,20,str(document.page))
 doc.build(story,onFirstPage=footer,onLaterPages=footer);return output.getvalue()

def export_xlsx(result,map_png,language='ru'):
 wb=Workbook();summary=wb.active;summary.title=t('Мониторинг','Мониторинг',language)
 summary.append(['EcoLogicDev',_safe(result['territory']['kk' if language=='kk' else 'ru'])]);summary.append([t('Период','Кезең',language),'2020 / 2026 · 06-01 — 08-31'])
 summary.append([t('Порог NDVI','NDVI шегі',language),result['threshold']]);summary.append([t('Показатель','Көрсеткіш',language),t('Значение','Мәні',language)])
 for key,ru,kk in LABELS:summary.append([kk if language=='kk' else ru,_value(key,result['statistics'].get(key))])
 chart_data=wb.create_sheet('NDVI');chart_data.append([t('Год','Жыл',language),'NDVI'])
 for year in (2020,2026):chart_data.append([year,result['statistics'][f'mean_ndvi_{year}']])
 chart=BarChart();chart.title=t('Средний сезонный NDVI','Орташа маусымдық NDVI',language);chart.y_axis.title='NDVI';chart.add_data(Reference(chart_data,min_col=2,min_row=1,max_row=3),titles_from_data=True);chart.set_categories(Reference(chart_data,min_col=1,min_row=2,max_row=3));chart_data.add_chart(chart,'D2')
 changes=wb.create_sheet(t('Карта','Карта',language));changes.append([t('Зелёный: прирост; красный: потеря; серый: без смены класса; прозрачный: нет данных.','Жасыл: өсім; қызыл: жоғалу; сұр: класс өзгермеген; мөлдір: дерек жоқ.',language)])
 image=ExcelImage(BytesIO(map_png));ratio=min(900/image.width,600/image.height);image.width*=ratio;image.height*=ratio;changes.add_image(image,'A3')
 sources=wb.create_sheet(t('Источники','Дереккөздер',language));sources.append(['Dataset',str(result.get('dataset_id'))]);sources.append([result['source']['attribution'],result['source']['catalog']]);sources.append([t('Методика','Әдістеме',language),'NDVI=(B08-B04)/(B08+B04); median; 10m; SCL 4,5,6; common mask; min observations=2/year'])
 for w in result['warnings']:sources.append([_safe(w)])
 sources.append([t('Год','Жыл',language),'ID',t('Дата','Күні',language),t('Облачность, %','Бұлттылық, %',language),t('Источник','Дереккөз',language)])
 for year,scene in _scenes(result):sources.append([year,_safe(scene['id']),scene.get('date',scene.get('datetime')),_safe(scene.get('cloud_cover')),_safe(scene.get('source',result['source']['catalog']))])
 for sheet in wb:
  sheet.freeze_panes='A2'
  for cell in sheet[1]:cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='174D3D')
  for col in sheet.columns:sheet.column_dimensions[col[0].column_letter].width=min(70,max(16,max(len(str(c.value or '')) for c in col)+2))
 output=BytesIO();wb.save(output);return output.getvalue()
