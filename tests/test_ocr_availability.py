"""Missing optional OCR must be unavailable, never empty successful evidence."""
from pathlib import Path
import pytest
from crystal_ball.config import load
from crystal_ball.senses import read
from crystal_ball.util import StageError


@pytest.mark.parametrize('failure',[FileNotFoundError('tesseract absent'),StageError('process','tesseract absent')])
def test_missing_ocr_stage_and_direct_api(tmp_path,monkeypatch,failure):
    from PIL import Image
    image=tmp_path/'input.png'
    Image.new('RGB',(32,32),'white').save(image)
    def absent(*args,**kwargs):
        raise failure
    monkeypatch.setattr(read,'command',absent)
    cfg=load()
    frame={'time':0.0,'path':str(image)}
    for value in (read.ocr_stage({'file':str(image),'review':{'frames':[frame]},'config':cfg}),
                  read._read_text(image,config=cfg)):
        assert 'lines' not in value  # no claim that OCR ran and found no text
        assert 'tesseract absent' in value['diagnostic']
        item=value['checks'][0]
        assert item['status']=='SKIP' and item['skip_reason']=='unavailable'
        assert item['summary']=='Not checked: OCR engine unavailable'
