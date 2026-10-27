from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO
from PySide6.QtCore import QThread, Signal, Qt, QTimer, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QPlainTextEdit, QMessageBox, QComboBox, QRadioButton
from engine import CountEngine

# nama kelas model -> label internal engine.
# COCO (pretrained): car/bus/truck. Model custom: kelas diberi nama MP, KS, BB, TB.
LABEL_ALIAS={'car':'MP','bus':'BUS','truck':'TRUK','mp':'MP','ks':'KS','bb':'BB','tb':'TB'}

class Reader(QThread):
    frame=Signal(object,str)
    def __init__(self,source,demo,referer=None,user_agent=None):
        super().__init__(); self.source=source; self.demo=demo; self.referer=referer; self.user_agent=user_agent; self.running=True
    def run(self):
        cap=None; t0=time.monotonic(); path=Path(self.source)
        if self.demo:
            while self.running:
                f=np.full((576,704,3),85,dtype=np.uint8); f[:]=40
                self.frame.emit(f,'demo'); self.msleep(35)
            return
        while self.running:
            if cap is None:
                cap=cv2.VideoCapture(self.source)
                if self.referer: cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,5000)
                if not cap.isOpened(): self.frame.emit(None,'reconnect'); cap.release(); cap=None; self.msleep(1500); continue
                fps=cap.get(cv2.CAP_PROP_FPS) or 25; delay=max(1,round(1000/fps)) if path.is_file() else 1
            ok,f=cap.read()
            if ok:
                self.frame.emit(f,'terhubung'); self.msleep(delay)
            elif path.is_file(): self.frame.emit(None,'selesai'); break
            else:
                self.frame.emit(None,'reconnect'); cap.release(); cap=None; self.msleep(1500)
        if cap: cap.release()

class VideoView(QLabel):
    pointClicked=Signal(float,float); dragPoint=Signal(float,float)
    def __init__(self): super().__init__('Menunggu frame'); self.setMinimumSize(704,576); self.setAlignment(Qt.AlignmentFlag.AlignCenter); self.setMouseTracking(True); self.pix=None; self.rois={}; self.edit=False; self.selected=''; self.phase='done'; self.drag=None; self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def set_frame(self,frame,rois):
        h,w=frame.shape[:2]; rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB); self.pix=QPixmap.fromImage(QImage(rgb.data,w,h,rgb.strides[0],QImage.Format.Format_RGB888).copy()); self.rois=rois; self.update()
    def mapping(self):
        if not self.pix:return 1,0,0
        scale=min(self.width()/self.pix.width(),self.height()/self.pix.height()); return scale,(self.width()-self.pix.width()*scale)/2,(self.height()-self.pix.height()*scale)/2
    def to_image(self,x,y):
        s,ox,oy=self.mapping(); return ((x-ox)/s,(y-oy)/s)
    def paintEvent(self,event):
        p=QPainter(self); p.fillRect(self.rect(),Qt.GlobalColor.black)
        if not self.pix:return
        s,ox,oy=self.mapping(); p.drawPixmap(int(ox),int(oy),int(self.pix.width()*s),int(self.pix.height()*s),self.pix); p.save();p.translate(ox,oy);p.scale(s,s)
        for n,r in self.rois.items():
            col=Qt.GlobalColor.yellow if self.edit and n==self.selected else Qt.GlobalColor.cyan if n=='Arah_Kanan' else Qt.GlobalColor.magenta
            p.setPen(QPen(col,2/s)); p.drawPolygon(QPolygonF([QPointF(*pt) for pt in r['polygon']]))
            for pt in r['polygon']:p.drawEllipse(QPointF(*pt),5/s,5/s)
            if r.get('line'):
                p.setPen(QPen(Qt.GlobalColor.green,3/s));p.drawLine(QPointF(*r['line'][0]),QPointF(*r['line'][1]))
                if self.edit and n==self.selected:
                    for pt in r['line']:p.drawEllipse(QPointF(*pt),7/s,7/s)
        if self.edit:
            p.setPen(QPen(Qt.GlobalColor.white));p.drawText(QPointF(12,24),f'Edit {self.selected} — drag titik untuk ubah; Backspace hapus titik terakhir, klik titik baru, Enter selesai')
        p.restore()
    def keyPressEvent(self,e):
        r=self.rois.get(self.selected)
        if not self.edit or r is None:return
        if e.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter) and self.phase=='poly' and len(r['polygon'])>=3:self.phase='done';self.update()
        elif e.key()==Qt.Key.Key_Backspace and r['polygon']:r['polygon'].pop();self.phase='poly';self.update()
    def mousePressEvent(self,e):
        if not self.edit or not self.pix:return
        self.setFocus();x,y=self.to_image(e.position().x(),e.position().y()); r=self.rois.get(self.selected)
        if r is None:return
        self.drag=next((('poly',i) for i,(px,py) in enumerate(r['polygon']) if (px-x)**2+(py-y)**2<100),None)
        if self.drag is None and r.get('line'):
            self.drag=next((('line',i) for i,(px,py) in enumerate(r['line']) if (px-x)**2+(py-y)**2<160),None)
        if self.drag is not None:return
        if self.phase=='poly':r['polygon'].append([round(x),round(y)])
        elif self.phase=='line':
            if len(r.get('line',[]))<2:r.setdefault('line',[]).append([round(x),round(y)])
            if len(r['line'])>=2:self.phase='done'
        self.update()
    def mouseMoveEvent(self,e):
        if self.edit and self.drag is not None:
            x,y=self.to_image(e.position().x(),e.position().y()); self.dragPoint.emit(x,y)
    def mouseReleaseEvent(self,e):self.drag=None

class Processor(QThread):
    rendered=Signal(object,object,float,str)
    def __init__(self,reader,engine,args): super().__init__(); self.reader=reader; self.engine=engine; self.args=args; self.lock=__import__('threading').Lock();self.latest=None;self.stream='menunggu';self.go=True;self.active=True;self.demo_n=0;reader.frame.connect(self.set_frame)
    def set_frame(self,f,status):
        with self.lock:self.stream=status
        if f is not None:
            with self.lock:self.latest=f.copy()
    def crop_box(self,shape):
        # area deteksi = kotak pembatas semua ROI + margin (dalam koordinat frame penuh)
        h,w=shape[:2]
        pts=[pt for r in self.engine.rois.values() for pt in r['polygon']]
        if self.args.no_crop or len(pts)<3:return 0,0,w,h
        m=self.args.crop_margin
        x0=max(0,int(min(p[0] for p in pts))-m);y0=max(0,int(min(p[1] for p in pts))-m)
        x1=min(w,int(max(p[0] for p in pts))+m);y1=min(h,int(max(p[1] for p in pts))+m)
        if x1-x0<64 or y1-y0<64:return 0,0,w,h
        return x0,y0,x1,y1
    def detect(self,model,label_map,frame):
        x0,y0,x1,y1=self.crop_box(frame.shape);sub=np.ascontiguousarray(frame[y0:y1,x0:x1]);dets=[]
        result=model.track(sub,persist=True,tracker='bytetrack.yaml',classes=self.classes,conf=self.args.conf,imgsz=self.args.imgsz,device=self.args.device,verbose=False)[0]
        if result.boxes.id is not None:
            for b,tid,cl,cf in zip(result.boxes.xyxy.cpu().numpy(),result.boxes.id.int().cpu().tolist(),result.boxes.cls.int().cpu().tolist(),result.boxes.conf.cpu().tolist()):dets.append((tid,label_map[cl],cf,(b[0]+x0,b[1]+y0,b[2]+x0,b[3]+y0)))
        return dets
    def run(self):
        # Baris penting untuk memperbaiki NameError
        model = None if self.args.demo else YOLO(self.args.model)
        last = 0

        if model is not None:
            label_map = {
                i: LABEL_ALIAS[n.lower()]
                for i, n in model.names.items()
                if n.lower() in LABEL_ALIAS
            }
            if not label_map:
                raise RuntimeError(
                    f"Nama kelas model tidak dikenali: {model.names}"
                )
            self.classes = list(label_map)

        model=None if self.args.demo else YOLO(self.args.model); last=0
        if model is not None:
            label_map={i:LABEL_ALIAS[n.lower()] for i,n in model.names.items() if n.lower() in LABEL_ALIAS}
            if not label_map: raise RuntimeError(f'Nama kelas model tidak dikenali: {model.names}')
            self.classes=list(label_map)
        while self.go:
            if not self.active:self.msleep(50);continue
            with self.lock:frame=self.latest;self.latest=None;stream=self.stream
            if frame is None:self.msleep(30);continue
            now=time.time(); dets=[]
            if self.args.demo:
                self.demo_n+=1; lane=self.demo_n%2; name=list(self.engine.rois)[lane]; poly=self.engine.rois[name]['polygon']; x=sum(p[0] for p in poly)/len(poly)
                phase=(self.demo_n%180)/180; top=min(p[1] for p in poly); bot=max(p[1] for p in poly)
                direction=self.engine.rois[name].get('direction','down')
                y=top+phase*(bot-top+60) if direction=='down' else bot-phase*(bot-top+60)
                tid=(self.demo_n//180)*2+lane+1; cls=('MP','BUS','TRUK')[(self.demo_n//180)%3];dets=[(tid,cls,.9,(x-18,y-30,x+18,y))]
            else:
                dets=self.detect(model,label_map,frame)
            events=self.engine.update(dets,now)
            for n,r in self.engine.rois.items():
                col=(255,0,255) if n=='Arah_Kiri' else (0,180,255);cv2.polylines(frame,[np.array(r['polygon'],dtype=np.int32)],True,col,2)
                if r.get('line'):
                    a,b=r['line'];cv2.line(frame,tuple(map(int,a)),tuple(map(int,b)),col,2)
                    cv2.putText(frame,f"{n} {r.get('direction','')}",(int(a[0]),int(a[1])-8),cv2.FONT_HERSHEY_SIMPLEX,.45,col,1)
            if not self.args.demo:
                h,w=frame.shape[:2];cb=self.crop_box(frame.shape)
                if cb!=(0,0,w,h):cv2.rectangle(frame,(cb[0],cb[1]),(cb[2]-1,cb[3]-1),(90,90,90),1)
            for tid,t in self.engine.tracks.items():
                x1,y1,x2,y2=map(int,t['box']); color=(0,200,0) if t['status']=='sudah dihitung' else (0,220,255) if t['status']=='di dalam ROI' else (150,150,150);cv2.rectangle(frame,(x1,y1),(x2,y2),color,2);cv2.putText(frame,f"{t['class']} #{tid}",(x1,y1-5),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1)
            elapsed=now-last;last=now;self.rendered.emit(frame,events,1/elapsed if elapsed else 0,stream)

class Window(QWidget):
    def __init__(self,args):
        super().__init__();self.args=args;self.setWindowTitle('Penghitung CCTV — DJ JBH6/2');self.roi_path=Path(args.rois);data=json.loads(self.roi_path.read_text(encoding='utf8'));self.rois={n:{'polygon':[list(pt) for pt in r['polygon']], 'line':[list(pt) for pt in r['line']], 'direction':r['direction']} for n,r in data['rois'].items()};self.ref=data.get('ref_size',[704,576]);self._roi_frame_size=None;self.engine=CountEngine(self.rois,args.lanes,args.lle,args.tb_share,args.bus_bb,args.window,3,args.warmup,args.stitch_sec);self.paused=False;self.edit=False
        self.video=VideoView();self.stats=QPlainTextEdit();self.stats.setReadOnly(True);self.log=QPlainTextEdit();self.log.setReadOnly(True);self.status=QLabel('menunggu');self.fps=QLabel('FPS proses: —')
        self.start=QPushButton('Jeda');self.start.clicked.connect(self.toggle);reset=QPushButton('Reset');reset.clicked.connect(self.reset);shot=QPushButton('Simpan screenshot');shot.clicked.connect(self.screenshot)
        edit=QPushButton('Edit ROI');edit.clicked.connect(self.edit_roi);save=QPushButton('Simpan ROI');save.clicked.connect(self.save_roi)
        self.tb=QLineEdit(str(args.tb_share));self.lanes=QLineEdit(str(args.lanes));self.bus=QLineEdit(str(args.bus_bb));self.roi_choice=QComboBox();self.roi_choice.addItems(list(self.rois));self.roi_choice.currentTextChanged.connect(self.change_roi);self.edit_mode=QComboBox();self.edit_mode.addItems(['Polygon','Garis hitung']);self.edit_mode.currentTextChanged.connect(self.change_edit_mode);self.direction=QComboBox();self.direction.addItems(['up','down']);self.direction.currentTextChanged.connect(self.change_direction)
        right=QVBoxLayout();right.addWidget(self.stats);right.addWidget(self.log);right.addWidget(self.status);right.addWidget(self.fps)
        form=QFormLayout();form.addRow('ROI',self.roi_choice);form.addRow('Mode edit',self.edit_mode);form.addRow('Arah',self.direction);form.addRow('tb_share',self.tb);form.addRow('lanes',self.lanes);form.addRow('bus_bb',self.bus);right.addLayout(form)
        for b in (self.start,reset,edit,save,shot):right.addWidget(b)
        layout=QHBoxLayout(self);layout.addWidget(self.video,3);layout.addLayout(right,1)
        self.reader=Reader(args.source,args.demo,args.referer,args.user_agent);self.processor=Processor(self.reader,self.engine,args);self.processor.rendered.connect(self.show_frame);self.reader.start();self.processor.start();self.video.pointClicked.connect(lambda x,y:None);self.video.dragPoint.connect(self.drag_vertex);self.timer=QTimer(self);self.timer.timeout.connect(self.update_stats);self.timer.start(500)
    def _sync_rois_to_frame(self, frame):
        h,w=frame.shape[:2]
        if self._roi_frame_size == (w,h): return
        rw,rh=self.ref
        if rw <= 0 or rh <= 0: return
        sx,sy=w/rw,h/rh
        if abs(sx-1) < 1e-6 and abs(sy-1) < 1e-6:
            self._roi_frame_size=(w,h); return
        # rois.json disimpan pada ref_size; engine dan editor harus memakai
        # koordinat frame aktual agar line/ROI tidak bergeser pada stream lain.
        for r in self.rois.values():
            r['polygon']=[[round(x*sx),round(y*sy)] for x,y in r['polygon']]
            r['line']=[[round(x*sx),round(y*sy)] for x,y in r.get('line',[])]
        self.ref=[w,h]
        self._roi_frame_size=(w,h)

    def show_frame(self,frame,events,fps,stream):
        self._sync_rois_to_frame(frame)
        self.video.set_frame(frame,self.rois)
        self.fps.setText(f'FPS proses: {fps:.1f}');self.status.setText(stream)
        for e in events:self.log.appendPlainText(f"{time.strftime('%H:%M:%S',time.localtime(e['time']))} | {e['direction']} | {e['class']} | {e['id']} | {e['via']}")
    def update_stats(self):
        try:
            self.engine.lanes=int(self.lanes.text());self.engine.tb_share=float(self.tb.text());self.engine.bus_bb=float(self.bus.text())
        except ValueError:pass
        now=time.time();self.stats.setPlainText('\n\n'.join(f"{n}\n"+' | '.join(f'{k}: {v}' for k,v in self.engine.summary(n,now).items()) for n in self.rois))
    def toggle(self):self.paused=not self.paused;self.processor.active=not self.paused;self.start.setText('Mulai' if self.paused else 'Jeda')
    def reset(self):self.engine.reset();self.log.clear()
    def screenshot(self):
        Path('out').mkdir(exist_ok=True);p=self.video.pixmap()
        if p:p.save('out/screenshot.png')
    def edit_roi(self):
        if not self.edit:
            self.edit=True;self.video.edit=True;self.change_roi(self.roi_choice.currentText());self.video.phase='poly' if self.edit_mode.currentText()=='Polygon' else 'line';self.paused=True;self.processor.active=False;self.start.setText('Mulai')
        else:self.edit=False;self.video.edit=False;self.video.phase='done';self.paused=False;self.processor.active=True;self.start.setText('Jeda');self.video.update()
    def change_roi(self,name):
        self.video.selected=name;self.video.phase='line' if self.edit_mode.currentText()=='Garis hitung' else 'done';self.direction.setCurrentText(self.rois[name].get('direction','down'));self.video.update()
    def change_edit_mode(self,mode):
        self.video.phase='line' if mode=='Garis hitung' and self.edit else 'poly' if mode=='Polygon' and self.edit else 'done';self.video.update()
    def change_direction(self,direction):
        if hasattr(self,'rois') and self.roi_choice.currentText() in self.rois:
            self.rois[self.roi_choice.currentText()]['direction']=direction

    def drag_vertex(self,x,y):
        if not self.edit or self.video.drag is None:return
        r=self.rois[self.video.selected]
        kind,index=self.video.drag
        if kind=='poly' and index<len(r['polygon']):r['polygon'][index]=[round(x),round(y)]
        elif kind=='line' and index<len(r.get('line',[])):r['line'][index]=[round(x),round(y)]
        self.video.update()
    def save_roi(self):
        bad=[n for n,r in self.rois.items() if len(r['polygon'])<3]
        if bad:QMessageBox.warning(self,'ROI belum lengkap',f"ROI {', '.join(bad)} butuh minimal 3 titik (klik titik, lalu Enter).");return
        self.rois[self.video.selected]['direction']=self.direction.currentText()
        self.roi_path.write_text(json.dumps({'ref_size':self.ref,'rois':self.rois},indent=2),encoding='utf8');self.engine.rois=self.rois;self.video.rois=self.rois
    def closeEvent(self,event):
        self.reader.running=False;self.processor.go=False;self.reader.wait(3000);self.processor.wait(5000);self.engine.write_csv('out');event.accept()

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',default='');p.add_argument('--rois',default='rois.json');p.add_argument('--lanes',type=int,default=3);p.add_argument('--lle',type=float,default=3.5);p.add_argument('--tb-share',type=float,default=.3);p.add_argument('--bus-bb',type=float,default=1.);p.add_argument('--window',type=int,default=300);p.add_argument('--warmup',type=int,default=60);p.add_argument('--model',default='yolo26s.pt');p.add_argument('--imgsz',type=int,default=640);p.add_argument('--conf',type=float,default=.3);p.add_argument('--device',default=None);p.add_argument('--referer');p.add_argument('--user-agent');p.add_argument('--crop-margin',type=int,default=40);p.add_argument('--stitch-sec',type=float,default=1.5);p.add_argument('--no-crop',action='store_true');p.add_argument('--demo',action='store_true');args=p.parse_args()
    if not args.demo and not args.source:p.error('--source diperlukan kecuali --demo')
    app=QApplication(sys.argv);w=Window(args);w.resize(1280,760);w.show();sys.exit(app.exec())
if __name__=='__main__':main()