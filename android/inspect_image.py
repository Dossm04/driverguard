"""Run the two downloaded research models on one local image, without network access."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
import onnxruntime as ort

def letterbox(image,side=640):
    w,h=image.size;scale=min(side/w,side/h);nw,nh=round(w*scale),round(h*scale)
    left,top=(side-nw)//2,(side-nh)//2
    canvas=Image.new('RGB',(side,side),(114,114,114));canvas.paste(image.resize((nw,nh),Image.Resampling.BILINEAR),(left,top))
    return np.asarray(canvas,dtype=np.float32).transpose(2,0,1)[None]/255,(scale,left,top)

def decode_cigarette(output,transform,size,threshold=.6):
    raw=np.asarray(output)[0]
    if raw.shape!=(7,8400):raise ValueError('Unexpected smoking model output')
    scale,left,top=transform;w,h=size
    selected=[]
    for i in np.flatnonzero(raw[4]>=threshold):
        cx,cy,bw,bh=raw[:4,i];score=float(raw[4,i])
        if not np.isfinite([cx,cy,bw,bh,score]).all() or bw<=0 or bh<=0:continue
        box=[max(0.,float((cx-bw/2-left)/scale)),max(0.,float((cy-bh/2-top)/scale)),
             min(float(w),float((cx+bw/2-left)/scale)),min(float(h),float((cy+bh/2-top)/scale))]
        if box[2]>box[0] and box[3]>box[1]:selected.append({'box':box,'score':score})
    kept=[]
    for det in sorted(selected,key=lambda d:d['score'],reverse=True):
        a=det['box'];area=(a[2]-a[0])*(a[3]-a[1]);overlap=False
        for prev in kept:
            b=prev['box'];inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            union=area+(b[2]-b[0])*(b[3]-b[1])-inter
            if union>0 and inter/union>.45:overlap=True;break
        if not overlap:kept.append(det)
    return kept

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('image',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parent;assets=root/'app/src/main/assets'
    image=Image.open(args.image).convert('RGB')
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    belt=ort.InferenceSession(str(assets/'seatbelt_classifier.onnx'),options,providers=['CPUExecutionProvider'])
    tensor=np.asarray(image.resize((224,224),Image.Resampling.BILINEAR),dtype=np.float32).transpose(2,0,1)[None]/255
    probabilities=belt.run(None,{'images':tensor})[0][0]
    smoke=ort.InferenceSession(str(assets/'smoking_yolov8.onnx'),options,providers=['CPUExecutionProvider'])
    tensor,transform=letterbox(image);detections=decode_cigarette(smoke.run(None,{'images':tensor})[0],transform,image.size)
    args.output.mkdir(parents=True,exist_ok=True)
    report={'status':'research_candidate','field_validated':False,'seatbelt_input':'whole image; must show one driver and torso',
            'seatbelt_scores':dict(zip(['no_seatbelt','seat_belt'],map(float,probabilities))),
            'cigarette_candidates':detections,'warning':'Scores are not a measured accuracy or proof of a violation'}
    (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    draw=ImageDraw.Draw(image)
    for d in detections:draw.rectangle(d['box'],outline='orange',width=3)
    draw.text((8,8),'RESEARCH CANDIDATE - NOT FIELD VALIDATED',fill='orange')
    image.save(args.output/'preview.jpg')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
