#!/usr/bin/env python3
"""Correlate DOS PTP hardware exchanges with the selected grandmaster log."""
import argparse,decimal,json,pathlib,re,statistics

def ns(value): return int(decimal.Decimal(value)*1_000_000_000)
def main():
 p=argparse.ArgumentParser();p.add_argument('dos');p.add_argument('grandmaster');p.add_argument('--out');a=p.parse_args()
 dos=json.loads(pathlib.Path(a.dos).read_text());rows=[]
 for line in dos['text'].splitlines():
  v=line.split(',')
  if len(v)==10 and v[0]=='PTP_CSV' and v[1].isdigit():
   t=list(map(ns,v[6:10]));offset=((t[1]-t[0])-(t[3]-t[2]))/2;delay=((t[1]-t[0])+(t[3]-t[2]))/2
   rows.append(dict(sync=int(v[1]),delay_sequence=int(v[2]),offset_ns=float(v[3]),delay_ns=float(v[4]),rate_ppb=int(v[5]),t_ns=t,recomputed_offset_ns=offset,recomputed_delay_ns=delay))
 gm=[json.loads(s) for s in pathlib.Path(a.grandmaster).read_text().splitlines() if s.strip()]
 t1=set();t4=set();max_errors=0
 for record in gm:
  g=record.get('grandmaster')
  if not g:continue
  max_errors=max(max_errors,g['timestamp_errors'])
  if g['flags']&4:t1.add((g['sync_sequence'],g['t1'][0]*1_000_000_000+g['t1'][1]))
  if g['flags']&8:t4.add((g['delay_sequence'],g['t4'][0]*1_000_000_000+g['t4'][1]))
 tail=rows[-40:];offsets=[r['offset_ns'] for r in tail]
 result=dict(records=len(rows),last_window_records=len(tail),last_window_mean_offset_ns=statistics.mean(offsets) if offsets else None,last_window_max_abs_offset_ns=max(map(abs,offsets)) if offsets else None,last_window_stddev_offset_ns=statistics.pstdev(offsets) if offsets else None,last_path_delay_ns=tail[-1]['delay_ns'] if tail else None,grandmaster_timestamp_errors=max_errors,t1_matches=sum((r['sync'],r['t_ns'][0]) in t1 for r in rows),t4_matches=sum((r['delay_sequence'],r['t_ns'][3]) in t4 for r in rows),arithmetic_matches=sum(abs(r['offset_ns']-r['recomputed_offset_ns'])<.001 and abs(r['delay_ns']-r['recomputed_delay_ns'])<.001 for r in rows),dos_stop_verified=bool(re.search(r'PTP exchanges: \d+, lease renewals: \d+, stopped: verified',dos['text'])),console_overflow=dos.get('overflow'),dos_prompt_returned=dos['text'].rstrip().endswith('C:\\>'),rows=rows)
 print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
 if a.out:pathlib.Path(a.out).write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
