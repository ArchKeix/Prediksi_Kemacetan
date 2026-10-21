from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO
from PySide6.QtCore import QThread, Signal, Qt, QTimer, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QPlainTextEdit, QMessageBox, QComboBox
from engine import CountEngine

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
    def __init__(self): super().__init__('Menunggu frame'); self.setMinimumSize(704,576); self.setAlignment(Qt.AlignmentFlag.AlignCenter); self.setMouseTracking(True); self.pix=None; self.rois={}; self.edit=False; self.selected=''; self.poly=[]; self.line=[]; self.phase='poly'; self.drag=None
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
            col=Qt.GlobalColor.cyan if n=='Cibitung' else Qt.GlobalColor.magenta
            p.setPen(QPen(col,2/s)); p.drawPolygon(QPolygonF([QPointF(*pt) for pt in r['polygon']])); p.drawLine(QPointF(*r['line'][0]),QPointF(*r['line'][1]))
            for pt in list(r['polygon'])+list(r['line']):p.drawEllipse(QPointF(*pt),5/s,5/s)
        if self.edit:
            p.setPen(QPen(Qt.GlobalColor.yellow,2/s));
            if len(self.poly)>1:p.drawPolyline(QPolygonF([QPointF(*pt) for pt in self.poly]))
            for pt in self.poly+self.line:p.drawEllipse(QPointF(*pt),5/s,5/s)
            if len(self.line)==2:p.drawLine(QPointF(*self.line[0]),QPointF(*self.line[1]))
            p.setPen(QPen(Qt.GlobalColor.white));p.drawText(QPointF(12,24),f'Edit {self.selected} — {"klik titik polygon, Enter selesai" if self.phase=="poly" else "klik dua titik garis"}; Backspace undo, drag titik untuk ubah')
        p.restore()
    def keyPressEvent(self,e):
        if e.key()==Qt.Key.Key_Return and self.edit and self.phase=='poly' and len(self.poly)>=3:self.phase='line';self.update()
        elif e.key()==Qt.Key.Key_Backspace and self.edit:
            if self.phase=='poly' and self.poly:self.poly.pop()
            elif self.line:self.line.pop()
            self.update()
    def mousePressEvent(self,e):
        if not self.edit or not self.pix:return
        x,y=self.to_image(e.position().x(),e.position().y()); r=self.rois.get(self.selected,{'polygon':[],'line':[]}); pts=list(r['polygon'])+list(r['line'])
        self.drag=next((i for i,(px,py) in enumerate(pts) if (px-x)**2+(py-y)**2<100),None)
        if self.drag is not None:return
        if self.phase=='poly':self.poly.append([round(x),round(y)])
        elif len(self.line)<2:self.line.append([round(x),round(y)])
        self.update()
    def mouseMoveEvent(self,e):
        if self.edit and self.drag is not None:
            x,y=self.to_image(e.position().x(),e.position().y()); self.dragPoint.emit(x,y)
    def mouseReleaseEvent(self,e):self.drag=None

class Processor(QThread):
    rendered=Signal(object,object,float,str)
    def __init__(self,reader,engine,args): super().__init__(); self.reader=reader; self.engine=engine; self.args=args; self.lock=__import__('threading').Lock();self.latest=None;self.stream='menunggu';self.go=True;self.demo_n=0;reader.frame.connect(self.set_frame)
    def set_frame(self,f,status):
        with self.lock:self.stream=status
        if f is not None:
            with self.lock:self.latest=f.copy()
    def run(self):
        model=None if self.args.demo else YOLO(self.args.model); last=0
        while self.go:
            with self.lock:frame=self.latest;self.latest=None;stream=self.stream
            if frame is None:self.msleep(30);continue
            now=time.time(); dets=[]
            if self.args.demo:
                self.demo_n+=1; lane=self.demo_n%2; direction=list(self.engine.rois)[lane]; r=self.engine.rois[direction]; poly=r['polygon']; x=sum(p[0] for p in poly)/len(poly); y=sum(p[1] for p in poly)/len(poly); line_y=sum(p[1] for p in r['line'])/2
                # periodic object sim follows each ROI's configured direction
                phase=(self.demo_n%180)/180; y=(min(p[1] for p in poly)+phase*(max(p[1] for p in poly)-min(p[1] for p in poly)))
                if r['direction']=='up':y=max(p[1] for p in poly)-phase*(max(p[1] for p in poly)-min(p[1] for p in poly))
                tid=(self.demo_n//180)*2+lane+1; cls=('MP','BUS','TRUK')[(self.demo_n//180)%3];dets=[(tid,cls,.9,(x-18,y-30,x+18,y))]
            else:
                result=model.track(frame,persist=True,tracker='bytetrack.yaml',classes=[2,5,7],conf=self.args.conf,imgsz=self.args.imgsz,device=self.args.device,verbose=False)[0]
                if result.boxes.id is not None:
                    for b,tid,cl,cf in zip(result.boxes.xyxy.cpu().numpy(),result.boxes.id.int().cpu().tolist(),result.boxes.cls.int().cpu().tolist(),result.boxes.conf.cpu().tolist()):dets.append((tid,{2:'MP',5:'BUS',7:'TRUK'}[cl],cf,tuple(b)))
            events=self.engine.update(dets,now)
            for n,r in self.engine.rois.items():
                col=(255,0,255) if n=='Cimanggis' else (0,180,255);cv2.polylines(frame,[np.array(r['polygon'],dtype=np.int32)],True,col,2);cv2.line(frame,*[tuple(map(int,p)) for p in r['line']],(255,255,0),2)
            for tid,t in self.engine.tracks.items():
                x1,y1,x2,y2=map(int,t['box']); color=(0,200,0) if t['status']=='sudah dihitung' else (0,220,255) if t['status']=='di dalam ROI' else (150,150,150);cv2.rectangle(frame,(x1,y1),(x2,y2),color,2);cv2.putText(frame,f"{t['class']} #{tid}",(x1,y1-5),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1)
            elapsed=now-last;last=now;self.rendered.emit(frame,events,1/elapsed if elapsed else 0,stream)

class Window(QWidget):
    def __init__(self,args):
        super().__init__();self.args=args;self.setWindowTitle('Penghitung CCTV — DJ JBH6/2');self.roi_path=Path(args.rois);data=json.loads(self.roi_path.read_text(encoding='utf8'));self.rois=data['rois'];self.ref=data.get('ref_size',[704,576]);self.engine=CountEngine(self.rois,args.lanes,args.lle,args.tb_share,args.bus_bb,args.window,3,args.warmup);self.paused=False;self.edit=False
        self.video=VideoView();self.stats=QPlainTextEdit();self.stats.setReadOnly(True);self.log=QPlainTextEdit();self.log.setReadOnly(True);self.status=QLabel('menunggu');self.fps=QLabel('FPS proses: —')
        self.start=QPushButton('Jeda');self.start.clicked.connect(self.toggle);reset=QPushButton('Reset');reset.clicked.connect(self.reset);shot=QPushButton('Simpan screenshot');shot.clicked.connect(self.screenshot)
        edit=QPushButton('Edit ROI');edit.clicked.connect(self.edit_roi);save=QPushButton('Simpan ROI');save.clicked.connect(self.save_roi)
        self.tb=QLineEdit(str(args.tb_share));self.lanes=QLineEdit(str(args.lanes));self.bus=QLineEdit(str(args.bus_bb));self.roi_choice=QComboBox();self.roi_choice.addItems(list(self.rois));self.roi_choice.currentTextChanged.connect(self.change_roi);self.direction=QComboBox();self.direction.addItems(('down','up'))
        right=QVBoxLayout();right.addWidget(self.stats);right.addWidget(self.log);right.addWidget(self.status);right.addWidget(self.fps);form=QFormLayout();form.addRow('ROI',self.roi_choice);form.addRow('Arah gerak',self.direction);form.addRow('tb_share',self.tb);form.addRow('lanes',self.lanes);form.addRow('bus_bb',self.bus);right.addLayout(form)
        for b in (self.start,reset,edit,save,shot):right.addWidget(b)
        layout=QHBoxLayout(self);layout.addWidget(self.video,3);layout.addLayout(right,1)
        self.reader=Reader(args.source,args.demo,args.referer,args.user_agent);self.processor=Processor(self.reader,self.engine,args);self.processor.rendered.connect(self.show_frame);self.reader.start();self.processor.start();self.video.pointClicked.connect(lambda x,y:None);self.video.dragPoint.connect(self.drag_vertex);self.timer=QTimer(self);self.timer.timeout.connect(self.update_stats);self.timer.start(500)
    def show_frame(self,frame,events,fps,stream):
        if self.edit:self.video.set_frame(frame,self.rois)
        else:self.video.set_frame(frame,self.rois)
        self.fps.setText(f'FPS proses: {fps:.1f}');self.status.setText(stream)
        for e in events:self.log.appendPlainText(f"{time.strftime('%H:%M:%S',time.localtime(e['time']))} | {e['direction']} | {e['class']} | {e['id']} | {e['via']}")
    def update_stats(self):
        try:
            self.engine.lanes=int(self.lanes.text());self.engine.tb_share=float(self.tb.text());self.engine.bus_bb=float(self.bus.text())
        except ValueError:pass
        now=time.time();self.stats.setPlainText('\n\n'.join(f"{n}\n"+' | '.join(f'{k}: {v}' for k,v in self.engine.summary(n,now).items()) for n in self.rois))
    def toggle(self):self.paused=not self.paused;self.processor.go=not self.paused;self.start.setText('Mulai' if self.paused else 'Jeda')
    def reset(self):self.engine.reset();self.log.clear()
    def screenshot(self):
        Path('out').mkdir(exist_ok=True);p=self.video.pixmap()
        if p:p.save('out/screenshot.png')
    def edit_roi(self):
        if not self.edit:
            self.edit=True;self.video.edit=True;self.change_roi(self.direction.currentText());self.processor.go=False;self.start.setText('Mulai')
        else:self.edit=False;self.video.edit=False;self.processor.go=True;self.start.setText('Jeda');self.video.update()
    def change_roi(self,name):
        self.video.selected=name;self.direction.setCurrentText(self.rois[name]['direction']);self.video.poly=[list(p) for p in self.rois[name]['polygon']];self.video.line=[list(p) for p in self.rois[name]['line']];self.video.phase='line';self.video.update()
    def drag_vertex(self,x,y):
        if not self.edit or self.video.drag is None:return
        idx=self.video.drag;name=self.video.selected;r=self.rois[name]
        if idx<len(r['polygon']):r['polygon'][idx]=[round(x),round(y)]
        else:r['line'][idx-len(r['polygon'])]=[round(x),round(y)]
        if r['line'][0][0]>r['line'][1][0]:r['line'].reverse()
        self.video.update()
    def save_roi(self):
        if self.edit:
            r=self.rois[self.video.selected]
            if len(self.video.poly)>=3:r['polygon']=[list(p) for p in self.video.poly]
            if len(self.video.line)==2:r['line']=sorted([list(p) for p in self.video.line],key=lambda p:p[0])
            r['direction']=self.direction.currentText()
        self.roi_path.write_text(json.dumps({'ref_size':self.ref,'rois':self.rois},indent=2),encoding='utf8');self.engine.rois=self.rois;self.video.rois=self.rois
    def closeEvent(self,event):
        self.reader.running=False;self.processor.go=False;self.reader.wait(3000);self.processor.wait(5000);self.engine.write_csv('out');event.accept()

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',default='');p.add_argument('--rois',default='rois.json');p.add_argument('--lanes',type=int,default=3);p.add_argument('--lle',type=float,default=3.5);p.add_argument('--tb-share',type=float,default=.3);p.add_argument('--bus-bb',type=float,default=1.);p.add_argument('--window',type=int,default=300);p.add_argument('--warmup',type=int,default=60);p.add_argument('--model',default='yolov8n.pt');p.add_argument('--imgsz',type=int,default=640);p.add_argument('--conf',type=float,default=.3);p.add_argument('--device',default=None);p.add_argument('--referer');p.add_argument('--user-agent');p.add_argument('--demo',action='store_true');args=p.parse_args()
    if not args.demo and not args.source:p.error('--source diperlukan kecuali --demo')
    app=QApplication(sys.argv);w=Window(args);w.resize(1280,760);w.show();sys.exit(app.exec())
if __name__=='__main__':main()
