"""Spelling-local evidence, Unicode hygiene and OCR combination regressions."""
import copy

import pytest

from crystal_ball.util import spelling_checks
from crystal_ball.senses import read


def lines(text, confidence=95, times=(1.0,2.0)):
    return [{'text':text,'confidence':confidence,'time':t} for t in times]


@pytest.mark.parametrize('text,target',[
    ('Alexiz','Alexis'), ('NEW PLACE','NEW PLACES'),
    ('مرحبا Alexiz','Alexis'), ('“Alexiz،”','Alexis'),
    ('Re\u0301ferencas','Réferences'), ('الكتابات','الكتاباتم'),
    ('Reference','References\u0338'),
    ("O'Connar","O'Connor"), ('Anne-Maria','Anne-Marie'),
    ('a'*79+'b'*21,'a'*79+'c'*21),
])
def test_corroborated_spelling(text,target):
    result=spelling_checks(lines(text),[target])
    assert len(result)==1
    finding=result[0]
    assert finding['id']=='ocr_spelling' and finding['status']=='WARN'
    assert finding['timestamps']==[[1.0,1.0],[2.0,2.0]]
    assert 'similarity >=79%, OCR confidence >=70, >=2 sampled frames' in finding['summary']
    assert finding['fix']=='inspect the timestamped frames and source text; correct and re-render if confirmed'


@pytest.mark.parametrize('text,target',[
    ('Alexis','Alexis'), ('Alex','Alexis'), ('Referen','References'),
    ('ferences','References'), ('alexiس','Alexis'), ('Alexis##','Alexis'),
    ('welc0me','welcome'), ('@@##','Alexis'), ('Alex_iz','Alexis'),
    ('Alexiz-','Alexis'), ('Аlexiz','Alexis'), ('Alexiz','Alexis##'),
    ('NEW @@## PLACE','NEW PLACES'), ('NEW','NEW PLACES'),
    ('NEW PLACES','NEW PLACEZ EXTRA'), ('Alexiz','سليكس'),
    ('a'*78+'b'*22,'a'*78+'c'*22), ('NE PLACE','NEW PLACES'),
])
def test_ineligible_or_exact_spelling(text,target):
    assert not spelling_checks(lines(text),[target])


@pytest.mark.parametrize('confidence',[69,101,None,True,'95',float('nan'),float('inf'),-1,10**400])
def test_invalid_confidence(confidence):
    assert not spelling_checks(lines('Alexiz',confidence),['Alexis'])


@pytest.mark.parametrize('time',[None,True,'1',float('nan'),float('inf'),-1])
def test_invalid_timestamp(time):
    assert not spelling_checks(lines('Alexiz',times=(time,2)),['Alexis'])


def test_missing_evidence_and_distinct_candidate_votes():
    assert not spelling_checks([{'time':2,'text':'Alexiz'}],['Alexis'],proper_only=True)
    assert not spelling_checks([{'time':t,'text':'Alexiz'} for t in (1,2)],['Alexis'])
    assert not spelling_checks([{'confidence':95,'text':'Alexiz'}]*2,['Alexis'])
    assert not spelling_checks(lines('Alexiz',times=(1,1)),['Alexis'])
    assert not spelling_checks(lines('Alexiz',times=(1,)),['Alexis'])
    assert not spelling_checks(lines('Alexiz',times=(1,))+lines('Alexiy',times=(2,)),['Alexis'])
    result=spelling_checks(lines('Alexiz',70,times=(3,1,3,2)),['Alexis','alexis'])
    assert len(result)==1 and result[0]['timestamps']==[[1,1],[2,2],[3,3]]
    assert result[0]['summary']=='Possible spelling: "alexiz" vs expected "Alexis" (similarity >=79%, OCR confidence >=70, >=2 sampled frames)'
    assert not spelling_checks(lines('alexiz'),['Alexis'],proper_only=True)


def test_nfc_exact_and_full_timestamp_retention():
    assert not spelling_checks(lines('Re\u0301ferences'),['Réferences'])
    result=spelling_checks(lines('Alexiz',times=range(10)),['Alexis'])
    assert len(result[0]['timestamps'])==10


def test_ocr_stage_deduplicates_vocabularies_without_changing_raw_data(monkeypatch):
    raw=lines('Alexiz')+lines('referencas')
    for line in raw:
        line['box']=[0,0,100,30]
    data={'lines':raw,'sizes':{'1.0':[720,1280],'2.0':[720,1280]},'languages':['eng']}
    original=copy.deepcopy(data)
    monkeypatch.setattr(read,'ocr_frames',lambda *args:data)
    req={'file':'synthetic.mp4','review':{'frames':[{}]},'platform':'shorts',
         'expect_text':['“Alexis,”'],'rules':{'terms':['Alexis','alexis','References']}}
    result=read.ocr_stage(req)
    spelling=[r for r in result['checks'] if r['id']=='ocr_spelling']
    assert len(spelling)==1 and 'alexiz' in spelling[0]['summary']
    assert data==original and result['boxes']==raw and result['lines']==raw
    assert any(r['id']=='expected_text' and r['status']=='WARN' for r in result['checks'])
    assert any(r['id']=='ocr_safe_zone' and r['status']=='FAIL' for r in result['checks'])
    assert any(r['id']=='ocr_arabic' and r['status']=='SKIP' for r in result['checks'])
