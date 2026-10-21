import pytest
from engine import CountEngine, capacity, emp_for, point_in_poly

ROIS={'Cibitung':{'polygon':[(0,0),(100,0),(100,100),(0,100)],'line':[(0,50),(100,50)],'direction':'down'},'Cimanggis':{'polygon':[(120,0),(220,0),(220,100),(120,100)],'line':[(120,50),(220,50)],'direction':'up'}}
def det(i,label,y): return (i,label,.9,(40,y-10,60,y))

def test_pkji():
    assert emp_for(1500)==(1.2,1.2,1.6); assert emp_for(1501)==(1.4,1.4,2.0)
    assert emp_for(3000)==(1.6,1.7,2.4); assert emp_for(4000)==(2.0,1.6,3.3)
    assert capacity(3,3.5)==7500; assert capacity(3,3.25)==7200; assert capacity(3,3.75)==7725

def test_roi_and_line_count_once():
    e=CountEngine(ROIS,warmup_sec=0)
    assert not point_in_poly((110,50),ROIS['Cibitung']['polygon'])
    e.update([det(1,'MP',40)],0); assert e.update([det(1,'MP',60)],1)[0]['via']=='line'
    assert not e.update([det(1,'MP',70)],2); assert not e.update([det(1,'MP',40)],3)

def test_fallback_and_persistent_counted_id():
    e=CountEngine(ROIS,min_hits=3)
    for t in range(3): e.update([det(3,'TRUK',40)],t)
    assert e.update([],3)[0]['via']=='fallback'
    e.update([det(3,'TRUK',40)],7); assert not e.update([det(3,'TRUK',60)],8)

def test_voting_and_warmup():
    e=CountEngine(ROIS,min_hits=20,warmup_sec=60)
    for i in range(5):e.update([(8,'TRUK',.8,(40,30,60,40))],i)
    e.update([(8,'BUS',.9,(40,30,60,40))],6)
    assert e.states[8]['class']=='TRUK'; assert e.summary('Cibitung',6)['DJ'] is None
    q=48+12*1.2+16.8*1.2+7.2*1.6
    assert q==pytest.approx(94.08)

def test_reverse_direction_ignored():
    e=CountEngine(ROIS)
    e.update([det(9,'MP',60)],0); assert not e.update([det(9,'MP',40)],1)

def test_infinite_line_extension_does_not_count():
    roi={'A':{'polygon':[(-10,-20),(200,-20),(200,100),(-10,100)],'line':[(0,50),(100,50)],'direction':'down'}}
    e=CountEngine(roi)
    e.update([(20,'MP',.9,(140,30,160,40))],0)
    assert not e.update([(20,'MP',.9,(140,60,160,70))],1)

def test_other_roi_not_incremented():
    e=CountEngine(ROIS,min_hits=10)
    e.update([(21,'MP',.9,(30,20,50,40))],0)
    assert e.cum[('Cibitung','MP')]==0 and e.cum[('Cimanggis','MP')]==0
