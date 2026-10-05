"""Score manually annotated frame-level presence. Unknown is never a negative."""
import argparse,csv,json
from pathlib import Path
CLASSES=['phone','cigarette','seatbelt_on','seatbelt_off']
def template(report,path):
    with open(path,'x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['video_sha256','seconds','class','present'])
        for row in report['observations']:
            for cls in CLASSES:w.writerow([report['video']['sha256'],row['seconds'],cls,'unknown'])
def score(report,labels,threshold=.6):
    truth={}
    valid_times={float(r['seconds']) for r in report['observations']}
    with open(labels,encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            if row['video_sha256']!=report['video']['sha256']:raise ValueError('Labels belong to another video')
            cls=row['class'];t=float(row['seconds']);v=row['present'].strip().lower()
            if cls not in CLASSES or t not in valid_times or v not in {'0','1','unknown'}:raise ValueError('Invalid annotation')
            key=(t,cls)
            if key in truth:raise ValueError('Duplicate annotation')
            truth[key]=v
    results={}
    for cls in CLASSES:
        c=dict(TP=0,FP=0,TN=0,FN=0,unknown=0)
        for row in report['observations']:
            label=truth.get((float(row['seconds']),cls),'unknown')
            if label=='unknown':c['unknown']+=1;continue
            pred=any(b['cls']==cls and b['conf']>=threshold for b in row['boxes'])
            c[('T' if pred==(label=='1') else 'F')+('P' if pred else 'N')]+=1
        c['precision']=c['TP']/(c['TP']+c['FP']) if c['TP']+c['FP'] else None
        c['recall']=c['TP']/(c['TP']+c['FN']) if c['TP']+c['FN'] else None
        c['reviewed_frames']=len(report['observations'])-c['unknown'];results[cls]=c
    return {'method':'manual frame-level binary presence, not bounding-box mAP or event metrics','video_sha256':report['video']['sha256'],'model_sha256':report['model']['sha256'],'threshold':threshold,'per_class':results,'field_validation_passed':False,'limitations':['Unreviewed/ambiguous frames excluded, never assumed negative.','One clip does not establish driver-independent accuracy.','This does not evaluate near-face gating, event duration or live camera alerts.']}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',required=True);p.add_argument('--template');p.add_argument('--labels');p.add_argument('--output',default='frame_metrics.json');p.add_argument('--threshold',type=float,default=.6)
    a=p.parse_args();r=json.loads(Path(a.report).read_text(encoding='utf-8'))
    if not 0<a.threshold<=1:p.error('threshold must be in (0,1]')
    if a.template:template(r,a.template)
    elif a.labels:
        result=score(r,a.labels,a.threshold);Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
    else:p.error('Use --template new.csv or --labels reviewed.csv')
