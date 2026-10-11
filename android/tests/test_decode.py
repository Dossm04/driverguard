import importlib.util
from pathlib import Path
import numpy as np
from PIL import Image
path=Path(__file__).resolve().parents[1]/'inspect_image.py'
spec=importlib.util.spec_from_file_location('inspection',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_wide_letterbox_restores_coordinates_and_suppresses_duplicates():
    _,tr=module.letterbox(Image.new('RGB',(1280,720)))
    raw=np.zeros((1,7,8400),np.float32)
    raw[0,:5,0]=[320,320,100,40,.9]
    raw[0,:5,1]=[321,320,100,40,.8]
    found=module.decode_cigarette(raw,tr,(1280,720))
    assert len(found)==1
    assert np.allclose(found[0]['box'],[540,320,740,400])

def test_person_or_smoke_is_not_cigarette():
    raw=np.zeros((1,7,8400),np.float32);raw[0,:4,0]=[320,320,100,100];raw[0,5:,0]=.99
    assert module.decode_cigarette(raw,(1,0,0),(640,640))==[]

def test_padding_and_invalid_boxes_are_rejected():
    raw=np.zeros((1,7,8400),np.float32)
    raw[0,:5,0]=[320,10,10,10,.9]
    raw[0,:5,1]=[float('nan'),320,100,40,.8]
    assert module.decode_cigarette(raw,(.5,0,140),(1280,720))==[]
