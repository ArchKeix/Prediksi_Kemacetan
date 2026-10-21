from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict, deque
from pathlib import Path


def emp_for(total):
    if total <= 1500: return 1.2, 1.2, 1.6
    if total <= 2750: return 1.4, 1.4, 2.0
    if total <= 3250: return 1.6, 1.7, 2.4
    return 2.0, 1.6, 3.3


def capacity(lanes=3, lle=3.5):
    points = ((3.25, .96), (3.5, 1.0), (3.75, 1.03))
    lle = min(max(lle, points[0][0]), points[-1][0])
    fc = next((a[1] + (lle-a[0])/(b[0]-a[0])*(b[1]-a[1]) for a,b in zip(points, points[1:]) if a[0] <= lle <= b[0]), points[-1][1])
    return lanes * 2500 * fc


def status_text(dj):
    if dj is None: return "mengumpulkan data"
    return "jenuh" if dj >= 1 else "rawan" if dj > .85 else "lancar"


def point_in_poly(point, polygon):
    x,y = point; inside = False
    for (xi,yi),(xj,yj) in zip(polygon, polygon[1:]+polygon[:1]):
        if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/(yj-yi)+xi: inside = not inside
    return inside


def side_of_line(point, line):
    (ax,ay),(bx,by)=line; x,y=point
    return (bx-ax)*(y-ay)-(by-ay)*(x-ax)


class CountEngine:
    def __init__(self, rois, lanes=3, lle=3.5, tb_share=.3, bus_bb=1., window_sec=300, min_hits=3, warmup_sec=60):
        self.rois=rois; self.lanes=lanes; self.lle=lle; self.tb_share=tb_share; self.bus_bb=bus_bb
        self.window_sec=window_sec; self.min_hits=min_hits; self.warmup_sec=warmup_sec; self.reset()

    def reset(self):
        self.events=[]; self.counted_ids=set(); self.states={}; self.tracks={}; self.cum=Counter(); self.last_event=None; self.flash=set(); self.started=None

    def update(self,dets,now):
        if self.started is None: self.started=now
        self.flash=set(); seen=set(); emitted=[]
        for tid,label,conf,box in dets:
            tid=int(tid); seen.add(tid); x1,y1,x2,y2=box; p=((x1+x2)/2,y2)
            name=next((n for n,r in self.rois.items() if point_in_poly(p,r['polygon'])),None)
            state=self.states.get(tid)
            if state is None and name: state={'roi':name,'hits':0,'votes':Counter(),'prev':None,'first':now,'last':now,'class':None}; self.states[tid]=state
            if state:
                state['last']=now
                if name==state['roi']:
                    state['hits']+=1
                    if label in ('MP','BUS','TRUK'): state['votes'][label]+=1
                    state['class']=state['votes'].most_common(1)[0][0] if state['votes'] else label
                    line=self.rois[state['roi']]['line']; side=side_of_line(p,line); prev=state['prev']; prev_point=state.get('prev_point'); direction=self.rois[state['roi']]['direction']
                    crossed=prev is not None and ((prev<=0<side) if direction=='down' else (prev>0>=side)) and self._crosses(prev,side,prev_point,p,line)
                    state['prev']=side; state['prev_point']=p
                    if crossed: self._count(tid,state,now,'line',emitted)
                if tid not in self.counted_ids and state['hits']>=self.min_hits and name!=state['roi']:
                    self._count(tid,state,now,'fallback',emitted)
            status='sudah dihitung' if tid in self.counted_ids else 'di dalam ROI' if state and name==state['roi'] else 'di luar ROI'
            self.tracks[tid]={'box':box,'status':status,'class':state['class'] if state else label,'roi':state['roi'] if state else name}
        for tid,s in list(self.states.items()):
            if tid not in seen and tid not in self.counted_ids and s['hits']>=self.min_hits and now-s['last']>=.5:
                self._count(tid,s,now,'fallback',emitted)
        for tid,s in list(self.states.items()):
            if now-s['last']>2:
                self.states.pop(tid)
                if tid in self.tracks: self.tracks.pop(tid)
        return emitted

    @staticmethod
    def _crosses(s1,s2,p1,p2,line):
        (ax,ay),(bx,by)=line; dx,dy=bx-ax,by-ay; den=s1-s2
        if not den or dx*dx+dy*dy == 0: return False
        t=s1/den
        ix=p1[0]+t*(p2[0]-p1[0]); iy=p1[1]+t*(p2[1]-p1[1])
        projection=((ix-ax)*dx+(iy-ay)*dy)/(dx*dx+dy*dy)
        return 0 <= projection <= 1

    def _count(self,tid,s,now,via,out):
        if tid in self.counted_ids:return
        label=s['class'] or 'MP'
        mapping={'MP': [('MP',1)],'BUS':[('BB',self.bus_bb),('KS',1-self.bus_bb)],'TRUK':[('TB',self.tb_share),('KS',1-self.tb_share)]}
        self.counted_ids.add(tid)
        for cls,share in mapping.get(label,[]):
            if share: self.events.append({'time':now,'roi':s['roi'],'class':cls,'id':tid,'via':via,'count':share}); self.cum[(s['roi'],cls)]+=share
        event={'time':now,'direction':s['roi'],'class':label,'id':tid,'via':via}; out.append(event); self.last_event=event; self.flash.add(s['roi'])

    def summary(self,roi_name,now):
        recent=[e for e in self.events if e['roi']==roi_name and now-e['time']<=self.window_sec]
        counts={c:sum(e['count'] for e in recent if e['class']==c) for c in ('MP','KS','BB','TB')}
        rates={k:v*3600/self.window_sec for k,v in counts.items()}; total=sum(rates.values()); eks,ebb,etb=emp_for(total)
        q=rates['MP']+rates['KS']*eks+rates['BB']*ebb+rates['TB']*etb; cap=capacity(self.lanes,self.lle)
        dj=q/cap if self.started is not None and now-self.started>=self.warmup_sec else None
        return {'counts':counts,'rates':rates,'total':total,'emp':{'KS':eks,'BB':ebb,'TB':etb},'q':q,'C':cap,'DJ':dj,'status':status_text(dj)}

    def write_csv(self,out_dir='out'):
        path=Path(out_dir); path.mkdir(parents=True,exist_ok=True)
        with (path/'events.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['time','direction','class','id','via']); w.writeheader(); w.writerows({k:e[k] for k in w.fieldnames} for e in self._unique_events())
        with (path/'ringkasan.csv').open('w',newline='',encoding='utf-8') as f:
            fields=['direction','class','count']; w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows({'direction':r,'class':c,'count':v} for (r,c),v in self.cum.items())

    def _unique_events(self):
        seen=set()
        for e in self.events:
            key=(e['time'],e['roi'],e['id'])
            if key not in seen:
                seen.add(key); yield {'time':e['time'],'direction':e['roi'],'class':e['class'],'id':e['id'],'via':e['via']}
