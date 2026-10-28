from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
import time

HOUR_SECONDS = 3600


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


def side_of_line(point, line):
    (ax, ay), (bx, by) = line
    x, y = point
    return (bx - ax) * (y - ay) - (by - ay) * (x - ax)


def _crosses_segment(previous, current, line):
    (ax, ay), (bx, by) = line
    px, py = previous
    qx, qy = current
    rx, ry = qx - px, qy - py
    sx, sy = bx - ax, by - ay
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-9:
        return False
    t = ((ax - px) * sy - (ay - py) * sx) / denominator
    u = ((ax - px) * ry - (ay - py) * rx) / denominator
    return 0 <= t <= 1 and 0 <= u <= 1


def point_in_poly(point, polygon):
    x,y = point; inside = False
    for (xi,yi),(xj,yj) in zip(polygon, polygon[1:]+polygon[:1]):
        if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/(yj-yi)+xi: inside = not inside
    return inside


class CountEngine:
    def __init__(self, rois, lanes=3, lle=3.5, tb_share=.3, bus_bb=1., min_hits=3, stitch_sec=1.5):
        self.rois=rois; self.lanes=lanes; self.lle=lle; self.tb_share=tb_share; self.bus_bb=bus_bb
        self.min_hits=min_hits; self.stitch_sec=stitch_sec; self.reset()

    def reset(self):
        self.events=[]; self.observations=[]; self.counted_ids=set(); self.states={}; self.tracks={}; self.cum=Counter(); self.last_event=None; self.flash=set(); self.started=None; self.recent_lost=[]; self.invalid_periods=set(); self.invalid_period_reasons=defaultdict(set)

    def mark_gap(self, now, reason='gangguan pengamatan'):
        """Mark the observation period containing now as incomplete."""
        if self.started is None:
            return
        period_index=int((now-self.started)//HOUR_SECONDS)
        self.invalid_periods.add(period_index)
        self.invalid_period_reasons[period_index].add(reason)

    def update(self,dets,now):
        # Aturan hitung: kendaraan MULAI dilacak saat titik bawah kotaknya masuk polygon ROI,
        # DIHITUNG saat titik itu keluar dari polygon (minimal min_hits frame di dalam ROI).
        # Cadangan: kalau track hilang di dalam ROI >= 0,5 dtk, dihitung juga (via 'hilang').
        # Penyambungan ID: kalau tracker kehilangan kendaraan lalu memberi ID baru di dekat posisi
        # perkiraannya (dalam stitch_sec detik), keduanya dianggap SATU kendaraan -> tidak dihitung dua kali.
        if self.started is None: self.started=now
        self.flash=set(); seen=set(); emitted=[]
        self.tracks={}   # hanya kendaraan yang terdeteksi di frame ini (dulu ID di luar ROI nggak pernah dihapus -> kotak hantu)
        self.recent_lost=[s for s in self.recent_lost if now-s['last']<=self.stitch_sec+1.]
        for tid,label,conf,box in dets:
            tid=int(tid); seen.add(tid); x1,y1,x2,y2=box; p=((x1+x2)/2,y2)
            name=next((n for n,r in self.rois.items() if point_in_poly(p,r['polygon'])),None)
            state=self.states.get(tid)
            if state is None and name:
                state={'id':tid,'roi':name,'hits':0,'votes':Counter(),'first':now,'last':now,'class':None,'first_point':p,'last_point':p,'p_prev':p,'t_prev':now,'v':(0.,0.),'last_box':box,'dup':None,'stitched':None,'prev_side':None}
                line=self.rois[name].get('line')
                if line:
                    state['prev_side']=side_of_line(p,line)
                if self.stitch_sec>0:
                    state['dup']=next((rl['id'] for rl in self.recent_lost if rl['roi']==name and 0<=now-rl['last']<=self.stitch_sec and self._gap(rl,p,now)[0]),None)
                self.states[tid]=state
            if state:
                previous_point=state['last_point']
                dt=now-state['t_prev']
                if dt>0:
                    raw=((p[0]-state['p_prev'][0])/dt,(p[1]-state['p_prev'][1])/dt); vx,vy=state['v']
                    state['v']=(.5*vx+.5*raw[0],.5*vy+.5*raw[1]); state['p_prev']=p; state['t_prev']=now
                state['last']=now; state['last_point']=p; state['last_box']=box
                if name==state['roi']:
                    state['hits']+=1
                    if label in ('MP','BUS','TRUK','KS','BB','TB'): state['votes'][label]+=max(1.,y2-y1)*float(conf)
                    state['class']=state['votes'].most_common(1)[0][0] if state['votes'] else label
                    line=self.rois[state['roi']].get('line')
                    if line:
                        previous_side=state['prev_side']
                        current_side=side_of_line(p,line)
                        direction=self.rois[state['roi']].get('direction','down')
                        crossed=(_crosses_segment(previous_point,p,line) and
                                 ((direction=='down' and previous_side is not None and previous_side<=0<current_side) or
                                  (direction=='up' and previous_side is not None and previous_side>0>=current_side)))
                        state['prev_side']=current_side
                        if crossed and tid not in self.counted_ids:
                            self._count(tid,state,now,'line',emitted)
                elif tid not in self.counted_ids and state['hits']>=self.min_hits:
                    pass
            status='sudah dihitung' if tid in self.counted_ids else 'di dalam ROI' if state and name==state['roi'] else 'di luar ROI'
            self.tracks[tid]={'box':box,'status':status,'class':state['class'] if state else label,'roi':state['roi'] if state else name}
        for tid,s in list(self.states.items()):
            if tid not in seen and tid not in self.counted_ids and s['hits']>=self.min_hits and self._fallback_direction_ok(s) and now-s['last']>=.5:
                succ=self._find_successor(tid,s,seen) if self.stitch_sec>0 else None
                if succ is not None: self._merge(tid,s,succ,now,emitted)
                else:
                    self._count(tid,s,now,'fallback',emitted)
                    if tid in self.counted_ids: self.recent_lost.append(s)
        for tid,s in list(self.states.items()):
            if now-s['last']>2:
                self.states.pop(tid)
                if tid in self.tracks: self.tracks.pop(tid)
        return emitted

    @staticmethod
    def _gap(a,point,t):
        # jarak titik 'point' (muncul pada waktu t) ke posisi PERKIRAAN state a (posisi terakhir + kecepatan x selisih waktu); True kalau di dalam gerbang
        dt=max(-.5,min(2.,t-a['last'])); vx,vy=a['v']; px=a['last_point'][0]+vx*dt; py=a['last_point'][1]+vy*dt
        x1,y1,x2,y2=a['last_box']; r=max(40.,1.5*max(x2-x1,y2-y1)); d=math.hypot(point[0]-px,point[1]-py)
        return d<=r,d

    def _fallback_direction_ok(self, state):
        direction=self.rois[state['roi']].get('direction')
        vy=state['v'][1]
        if abs(vy) < 1e-6 or direction not in ('up', 'down'):
            return True
        return vy < 0 if direction == 'up' else vy > 0

    def _find_successor(self,tid,s,seen):
        best=None; bd=None
        for t2,s2 in self.states.items():
            if t2==tid or t2 not in seen or t2 in self.counted_ids or s2['roi']!=s['roi'] or s2['dup'] is not None: continue
            if s2['first']<s['last']-1.: continue
            near,d=self._gap(s,s2['first_point'],s2['first'])
            if near and (bd is None or d<bd): best,bd=t2,d
        return best

    def _merge(self,tid,s,t2,now,out):
        s2=self.states[t2]
        for k,v in s['votes'].items(): s2['votes'][k]+=v
        s2['hits']+=s['hits']; s2['first']=min(s2['first'],s['first']); s2['stitched']=tid
        s2['class']=s2['votes'].most_common(1)[0][0] if s2['votes'] else s2['class']
        self.counted_ids.add(tid)
        self._count(t2,s2,now,'stitch',out)

    def _count(self,tid,s,now,via,out):
        if tid in self.counted_ids:return
        if s.get('dup') is not None:
            self.counted_ids.add(tid); out.append({'time':now,'direction':s['roi'],'class':s['class'] or 'MP','id':tid,'via':f"duplikat #{s['dup']}"}); return
        label=s['class'] or 'MP'
        mapping={'MP': [('MP',1)],'KS':[('KS',1)],'BB':[('BB',1)],'TB':[('TB',1)],'BUS':[('BB',self.bus_bb),('KS',1-self.bus_bb)],'TRUK':[('TB',self.tb_share),('KS',1-self.tb_share)]}
        self.counted_ids.add(tid)
        observation={'time':now,'roi':s['roi'],'class':label,'id':tid,'via':via}
        self.observations.append(observation)
        for cls,share in mapping.get(label,[]):
            if share: self.events.append({'time':now,'roi':s['roi'],'class':cls,'id':tid,'via':via,'count':share}); self.cum[(s['roi'],cls)]+=share
        event={'time':now,'direction':s['roi'],'class':label,'id':tid,'via':via}; out.append(event); self.last_event=event; self.flash.add(s['roi'])

    @staticmethod
    def _period_timestamp(value):
        return datetime.fromtimestamp(value).astimezone().isoformat(timespec='seconds')

    def _period_summary(self,roi_name,period_index,now):
        period_start=self.started+period_index*HOUR_SECONDS
        period_end=period_start+HOUR_SECONDS
        complete=now>=period_end
        observed_end=min(now,period_end)
        counts={c:0. for c in ('MP','KS','BB','TB')}
        observed={'MP':0,'KS':0,'BB':0,'TB':0,'BUS':0,'TRUK':0}
        for event in self.events:
            if (event['roi']==roi_name and period_start<=event['time']<observed_end
                    and int((event['time']-self.started)//HOUR_SECONDS)==period_index):
                counts[event['class']]+=event['count']
        for event in self.observations:
            if (event['roi']==roi_name and period_start<=event['time']<observed_end
                    and int((event['time']-self.started)//HOUR_SECONDS)==period_index):
                observed[event['class']]+=1

        valid=complete and period_index not in self.invalid_periods
        if complete:
            rates=counts.copy()
            total=sum(observed.values())
            eks,ebb,etb=emp_for(total)
            q=rates['MP']+rates['KS']*eks+rates['BB']*ebb+rates['TB']*etb
            dj=q/capacity(self.lanes,self.lle)
            status=status_text(dj) if valid else f"{status_text(dj)} (estimasi; data tidak lengkap)"
            emp={'KS':eks,'BB':ebb,'TB':etb}
        else:
            rates=None; total=None; q=None; dj=None; emp=None
            status='periode tidak lengkap' if period_index in self.invalid_periods else 'mengumpulkan data'
        invalid_reasons=sorted(self.invalid_period_reasons.get(period_index,()))
        return {
            'counts':counts,'rates':rates,'total':total,'emp':emp,'q':q,
            'C':capacity(self.lanes,self.lle),'DJ':dj,'status':status,
            'period_start':period_start,'period_end':period_end,
            'period_complete':complete,'period_valid':valid,
            'observed':observed,'invalid_reasons':invalid_reasons,
        }

    def summary(self,roi_name,now):
        if self.started is None:
            return {
                'counts':{c:0. for c in ('MP','KS','BB','TB')},
                'rates':None,'total':None,'emp':None,'q':None,
                'C':capacity(self.lanes,self.lle),'DJ':None,
                'status':'mengumpulkan data','period_start':None,
                'period_end':None,'period_complete':False,'period_valid':False,
                'observed':{'MP':0,'KS':0,'BB':0,'TB':0,'BUS':0,'TRUK':0},
                'invalid_reasons':[],
            }
        elapsed=max(0.,now-self.started)
        completed_index=int(elapsed//HOUR_SECONDS)-1
        period_index=completed_index if completed_index>=0 else 0
        return self._period_summary(roi_name,period_index,now)

    def _hourly_rows(self,now):
        if self.started is None:
            return
        elapsed=max(0.,now-self.started)
        period_count=max(1,math.ceil(elapsed/HOUR_SECONDS))
        for period_index in range(period_count):
            for roi_name in self.rois:
                data=self._period_summary(roi_name,period_index,now)
                counts=data['counts']; observed=data['observed']
                emp=data['emp'] or {}
                capacity_value=data['C']
                c0=2500
                fcle=capacity_value/(self.lanes*c0) if self.lanes else 0
                yield {
                    'period_start':self._period_timestamp(data['period_start']),
                    'period_end':self._period_timestamp(data['period_end']),
                    'observed_seconds':round(min(HOUR_SECONDS,max(0.,now-data['period_start'])),3),
                    'direction':roi_name,
                    'period_complete':data['period_complete'],
                    'period_valid':data['period_valid'],
                    'status':data['status'],
                    'invalid_reasons':'; '.join(data['invalid_reasons']),
                    'vehicles_total':sum(observed.values()),
                    'observed_mp':observed['MP'],
                    'observed_ks':observed['KS'],
                    'observed_bb':observed['BB'],
                    'observed_tb':observed['TB'],
                    'observed_bus':observed['BUS'],
                    'observed_truck':observed['TRUK'],
                    'ks_smp_equiv':round(counts['KS'],3),
                    'bb_smp_equiv':round(counts['BB'],3),
                    'tb_smp_equiv':round(counts['TB'],3),
                    'emp_ks':emp.get('KS'),
                    'emp_bb':emp.get('BB'),
                    'emp_tb':emp.get('TB'),
                    'q_smp_per_hour':round(data['q'],3) if data['q'] is not None else '',
                    'capacity_smp_per_hour':round(capacity_value,3),
                    'dj':round(data['DJ'],8) if data['DJ'] is not None else '',
                    'lanes':self.lanes,
                    'lle_m':self.lle,
                    'c0_smp_per_lane':c0,
                    'fcle':round(fcle,4),
                    'tb_share':self.tb_share,
                    'bus_bb':self.bus_bb,
                }

    def write_csv(self,out_dir='out',now=None):
        if now is None:
            now=time.time()
        path=Path(out_dir); path.mkdir(parents=True,exist_ok=True)
        with (path/'events.csv').open('w',newline='',encoding='utf-8') as f:
            fields=['time','direction','class','id','via'];w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
            w.writerows({'time':e['time'],'direction':e['roi'],'class':e['class'],'id':e['id'],'via':e['via']} for e in self.observations)
        with (path/'ringkasan.csv').open('w',newline='',encoding='utf-8') as f:
            fields=['direction','class','count']; w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows({'direction':r,'class':c,'count':v} for (r,c),v in self.cum.items())
        with (path/'ringkasan_jam.csv').open('w',newline='',encoding='utf-8') as f:
            fields=[
                'period_start','period_end','observed_seconds','direction',
                'period_complete','period_valid','status','vehicles_total',
                'invalid_reasons',
                'observed_mp','observed_ks','observed_bb','observed_tb',
                'observed_bus','observed_truck','ks_smp_equiv','bb_smp_equiv',
                'tb_smp_equiv','emp_ks','emp_bb','emp_tb','q_smp_per_hour',
                'capacity_smp_per_hour','dj','lanes','lle_m',
                'c0_smp_per_lane','fcle','tb_share','bus_bb',
            ]
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
            w.writerows(self._hourly_rows(now))

    def _unique_events(self):
        seen=set()
        for e in self.events:
            key=(e['time'],e['roi'],e['id'])
            if key not in seen:
                seen.add(key); yield {'time':e['time'],'direction':e['roi'],'class':e['class'],'id':e['id'],'via':e['via']}