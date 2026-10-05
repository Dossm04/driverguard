import { test, expect } from "@playwright/test";
import { decodeObjects, objectSignals, validateManifest, OBJECT_CLASSES } from "../../lib/dms/objects";
import { RuleEngine } from "../../lib/dms/rules";
import type { FrameSignals } from "../../lib/dms/signals";

test("letterbox inverses landscape coordinates; NMS keeps overlapping different classes", () => {
  const rows = [[320,320,160,160,.9,0,0,0],[321,321,160,160,.8,0,0,0],[320,320,160,160,0,.85,0,0]];
  const data = Array.from({length:8},(_,c)=>rows.map((r)=>r[c])).flat();
  const boxes=decodeObjects(data,[1,8,3],640,480);
  expect(boxes.map((b)=>b.cls)).toEqual(["phone","cigarette"]);
  expect(boxes[0].x1).toBeCloseTo(.375);expect(boxes[0].y1).toBeCloseTo(1/3);
});
test("wrong class count and NMS-export output are rejected",()=>{
  expect(()=>decodeObjects(new Float32Array(84),[1,84,1],640,480)).toThrow();
  expect(()=>decodeObjects(new Float32Array(6),[1,1,6],640,480)).toThrow();
});
test("NaN scores and padding-only boxes do not trigger warnings",()=>{
  expect(decodeObjects([320,20,40,20,.9,0,0,0],[1,8,1],640,480)).toHaveLength(0);
  expect(decodeObjects([320,320,40,20,NaN,0,0,0],[1,8,1],640,480)).toHaveLength(0);
});
test("stale or faceless observations never trigger objects",()=>{
  const boxes=[{cls:"phone" as const,conf:.9,x1:.4,x2:.6,y1:.4,y2:.6}];
  const face=[{x:.3,y:.2,z:0},{x:.7,y:.7,z:0}];
  expect(objectSignals(boxes,face,true).phoneConf).toBe(.9);
  expect(objectSignals(boxes,face,false).phoneConf).toBe(0);
  expect(objectSignals(boxes,undefined,true).phoneConf).toBe(0);
  expect(objectSignals([],face,true).seatbeltOffConf).toBe(0);
});
test("class order and model hash are mandatory",()=>{
  const m={schema:1,classes:OBJECT_CLASSES,input_size:640,sha256:"a".repeat(64),run_id:"test",status:"candidate"};
  expect(validateManifest(m)).toEqual(m);
  expect(()=>validateManifest({...m,classes:[...OBJECT_CLASSES].reverse()})).toThrow();
  expect(()=>validateManifest({...m,sha256:"abc"})).toThrow();
});
function scenario(over:Partial<FrameSignals>, duration=4000){
  const e=new RuleEngine({CALIB_FRAMES:1});let output=[] as ReturnType<RuleEngine["process"]>;
  for(let t=100;t<duration+100;t+=100)output.push(...e.process({tMs:t,face:true,eyeClose:0,ear:.3,jaw:0,pitch:0,yaw:0,speedKmh:40,phoneConf:0,smokeConf:0,...over}));
  return {e,output};
}
test("explicit no-seatbelt held 3 seconds while moving triggers one event",()=>{
  expect(scenario({seatbeltOffConf:.9}).output.map((d)=>d.type)).toEqual(["seatbelt"]);
  expect(scenario({seatbeltOffConf:.9},2000).output).toHaveLength(0);
});
test("unknown, on/off conflict, stationary and no-face never imply no seatbelt",()=>{
  for(const over of [{},{seatbeltOffConf:.9,seatbeltOnConf:.8},{seatbeltOffConf:.9,speedKmh:0},{seatbeltOffConf:.9,face:false}])
    expect(scenario(over).output).toHaveLength(0);
});
