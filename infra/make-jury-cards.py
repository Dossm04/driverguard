"""Regenerate jury QR cards from the current HTTPS address and local demo accounts."""
from pathlib import Path
from urllib.parse import urlencode
import argparse
import json
import subprocess
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget

parser=argparse.ArgumentParser()
parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1])
parser.add_argument('--accounts',type=Path)
parser.add_argument('--output',type=Path)
args=parser.parse_args()
project=args.project
state=json.loads((project/'.runtime/phone-state.json').read_text(encoding='utf-8-sig'))
assert state['Active'],'Run START_PHONE.cmd first.'
accounts=json.loads((args.accounts or project/'.runtime/jury-accounts.json').read_text(encoding='utf-8-sig'))
base=state['WebUrl'].rstrip('/')
assert base.startswith('https://') and base.endswith('.trycloudflare.com')
out=args.output or project.parent/'Жюри'
out.mkdir(parents=True,exist_ok=True)
pdfmetrics.registerFont(TTFont('DG',r'C:\Windows\Fonts\arial.ttf'))
pdfmetrics.registerFont(TTFont('DGB',r'C:\Windows\Fonts\arialbd.ttf'))
W,H=landscape(A4)
navy=colors.HexColor('#0B1923');mint=colors.HexColor('#B9F5D3');muted=colors.HexColor('#B2C4CE')
file=out/'DriverGuard_Жюри_QR.pdf'
c=canvas.Canvas(str(file),pagesize=(W,H))
c.setTitle('DriverGuard — QR и вход для жюри')
c.setAuthor('DriverGuard')

def text(x,y,value,size=14,color=colors.white,bold=False):
    c.setFillColor(color);c.setFont('DGB' if bold else 'DG',size);c.drawString(x,y,value)

def base_page(title,subtitle,number):
    c.setFillColor(navy);c.rect(0,0,W,H,fill=1,stroke=0)
    text(42,H-40,'DRIVERGUARD   /   ЖИВОЕ ДЕМО',12,mint,True)
    text(42,H-96,title,34,colors.white,True)
    text(42,H-124,subtitle,13,muted)
    c.setStrokeColor(colors.HexColor('#2B414E'));c.line(42,49,W-42,49)
    text(42,29,'Временная ссылка. Ноутбук и Docker должны оставаться включёнными.',10,muted)
    text(W-67,29,f'{number:02}',10,mint,True)

def qr(url,x=42,y=154,size=274):
    c.setFillColor(colors.white);c.roundRect(x-10,y-10,size+20,size+20,14,stroke=0,fill=1)
    widget=QrCodeWidget(url,barLevel='M')
    x0,y0,x1,y1=widget.getBounds(); drawing=Drawing(size,size,transform=[size/(x1-x0),0,0,size/(y1-y0),0,0]);drawing.add(widget)
    renderPDF.draw(drawing,c,x,y)
    return drawing

landing=base+'/jury.html'
base_page('Попробуйте DriverGuard','Откройте QR в Safari на iPhone или в Chrome на Android.',1)
drawing=qr(landing)
renderSVG.drawToFile(drawing,str(out/'QR_общий.svg'))
text(366,425,'Вход для участников',22,mint,True)
text(366,395,'Профиль',11,muted,True);text(452,395,'Учебный номер',11,muted,True);text(666,395,'PIN',11,muted,True)
for i,a in enumerate(accounts):
    y=361-i*40
    text(366,y,f'{i+1:02}',19,mint,True);text(452,y,a['phone'],18,colors.white);text(666,y,a['pin'],22,colors.white,True)
text(366,135,'Выберите свой профиль, введите PIN',14)
text(366,113,'и нажмите «Включить камеру».',14)
text(42,87,'Смотрите прямо до конца калибровки. Проверяйте сидя на месте.',13,muted)
c.linkURL(landing,(42,144,326,438),relative=0)
c.showPage()
links=[]
for i,a in enumerate(accounts,1):
    url=base+'/driver/login?'+urlencode({'phone':a['phone'],'next':'camera'})
    links.append({'name':a['name'],'url':url})
    base_page(f'Ваша проверка · участник {i:02}','Сканируйте QR. Номер заполнится автоматически; введите свой PIN.',i+1)
    qr(url)
    text(369,409,'УЧЕБНЫЙ НОМЕР',11,muted,True)
    text(369,374,a['phone'],28,colors.white,True)
    text(369,322,'PIN ДЛЯ ВХОДА',11,muted,True)
    text(369,277,a['pin'],44,mint,True)
    text(369,219,'Разрешите камеру. Смотрите прямо.',14)
    text(369,193,'Дождитесь завершения калибровки.',14)
    text(369,151,'Закройте глаза на 2-3 секунды.',14)
    text(369,125,'Проверьте сигнал и новое событие.',14)
    text(42,87,'Не сворачивайте браузер и не блокируйте экран во время проверки.',13,muted)
    c.linkURL(url,(42,144,326,438),relative=0)
    c.showPage()
c.save()
poppler=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe'
if poppler.is_file():
    subprocess.run([str(poppler),'-f','1','-singlefile','-r','120','-png',str(file),str(out/'QR_на_экран')],check=True)
(out/'QR_ссылки.json').write_text(json.dumps({'public_page':landing,'participants':links},ensure_ascii=False,indent=2),encoding='utf-8')
(out/'Вход_для_жюри.txt').write_text('DRIVERGUARD — ВХОД ДЛЯ ЖЮРИ\n\n'+landing+'\n\n'+'\n'.join(f"{a['name']}: {a['phone']}  PIN {a['pin']}" for a in accounts)+'\n\nЭто учебные учётные записи водителей. Пароль администратора жюри не нужен.\nКаждый участник выбирает отдельный профиль. На iPhone открыть Safari.\nСсылка работает, пока запущены текущие HTTPS-туннели и ноутбук не спит.\nПосле изменения адреса: UPDATE_JURY_QR.cmd, затем использовать новый PDF.\nЗакончить показ: STOP_PHONE.cmd, дождаться возврата локальных адресов.\n',encoding='utf-8-sig')
print(json.dumps({'pdf':str(file),'pages':len(accounts)+1,'public_page':landing},ensure_ascii=False))
