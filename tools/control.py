#!/usr/bin/env python3
"""Start, inspect or stop a PTP4D follower and its selected TimeStick grandmaster."""
import argparse, json, pathlib, shlex, subprocess, sys
SSH = ['ssh', '-T', '-oBatchMode=yes', '-oConnectTimeout=8']
REQUIRED = ('serial_host', 'peer_host', 'comrade_dir', 'serial_device', 'serial_lock',
            'dos_log_dir', 'peer_dir', 'peer_serial', 'peer_mac')

def load_config(path):
    settings = json.loads(pathlib.Path(path).read_text())
    if not isinstance(settings, dict):
        raise ValueError('Configuration must be a JSON object')
    for key in REQUIRED:
        if not isinstance(settings.get(key), str) or not settings[key].strip():
            raise ValueError(f'Missing configuration: {key}')
    for key in ('comrade_dir', 'serial_device', 'serial_lock', 'dos_log_dir', 'peer_dir'):
        if not settings[key].startswith('/'):
            raise ValueError(f'{key} must be an absolute remote path')
    for key in ('serial_host', 'peer_host'):
        if settings[key].startswith('-') or any(c.isspace() for c in settings[key]):
            raise ValueError(f'Invalid SSH destination: {key}')
    settings.setdefault('dos_executable', r'C:\PTP4D.EXE')
    settings.setdefault('dos_prompt', 'C:\\>')
    settings.setdefault('baud', 115200)
    for key in ('dos_executable', 'dos_prompt'):
        if not isinstance(settings[key], str) or not settings[key].strip():
            raise ValueError(f'Invalid configuration: {key}')
    if type(settings['baud']) is not int or settings['baud'] <= 0:
        raise ValueError('baud must be a positive integer')
    return settings

def remote(host, command, stdin=None, check=True):
    result = subprocess.run([*SSH, host, command], input=stdin, text=True,
                            capture_output=True, timeout=40)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result

RPC = r'''
import asyncio,json,pathlib,time
from comrade import server
server.CONFIG.update(transport='serial',device=settings['serial_device'],baud=settings['baud'])
async def main():
 async with server._lifespan(server.mcp):
  logs=pathlib.Path(settings['dos_log_dir']);logs.mkdir(parents=True,exist_ok=True)
  view=await server.screen_read();lines=view['text'].splitlines();row=view['cursor']['row']
  current=lines[row].strip() if row<len(lines) else '';prompt=current.startswith(settings['dos_prompt'])
  if action=='preflight':
   if not prompt:raise RuntimeError('PC is not at its DOS prompt; stop its foreground program first.')
   print(json.dumps({'ready':True}));return
  if action=='start':
   if not prompt:raise RuntimeError('DOS prompt changed before start.')
   result=await server.run_command(settings['dos_executable']+' /PTP '+str(seconds),timeout=4,idle_ms=3500)
   view=await server.screen_read();result['screen']=view
   (logs/'last-start.json').write_text(json.dumps(result,indent=2))
   if view['text'].rstrip().endswith(settings['dos_prompt']):raise RuntimeError(result['text'])
   print(json.dumps(result));return
  if action=='stop' and not prompt:
   if not any(name in view['text'] for name in ('PTP4D ', 'PTP ')):
    raise RuntimeError('Foreground screen does not identify PTP4D; refusing unrelated keystrokes.')
   cm=server._cm();seq=(await cm.read_console(0xFFFFFFFF,0))['next_seq'];parts=[];overflow=False
   await server.keys_send('{Esc}');end=time.monotonic()+12
   while time.monotonic()<end:
    await asyncio.sleep(.15)
    while True:
     chunk=await cm.read_console(seq,cm.chunk_max or 1024);seq=chunk['next_seq'];overflow|=chunk['overflow']
     if not chunk['data']:break
     parts.append(server.console_mod.to_text(chunk['data']))
    view=await server.screen_read()
    if view['text'].rstrip().endswith(settings['dos_prompt']):break
   result={'text':''.join(parts),'overflow':overflow,'screen':view}
   (logs/'last-stop.json').write_text(json.dumps(result,indent=2))
   if not view['text'].rstrip().endswith(settings['dos_prompt']):raise RuntimeError('PTP4D did not return to DOS.')
   print(json.dumps(result));return
  print(json.dumps(view))
asyncio.run(main())
'''

def dos(settings, action, seconds=0):
    code='settings='+repr(settings)+'\naction='+repr(action)+'\nseconds='+repr(seconds)+'\n'+RPC
    command='cd '+shlex.quote(settings['comrade_dir'])+' && '+shlex.join([
        'flock','-n','-E','75',settings['serial_lock'],'env',
        'COMRADE_KEY_DELAY_MS=100','COMRADE_KEY_BATCH=1','.venv/bin/python','-u','-'])
    return json.loads(remote(settings['serial_host'],command,code).stdout)

def peer_start_command(settings, seconds):
    directory=settings['peer_dir']
    args=['systemd-run','--user','--unit=ptp4d-gm','--collect','-p','TimeoutStopSec=8',
          '-p','StandardOutput=append:'+directory+'/grandmaster.jsonl',
          '-p','StandardError=append:'+directory+'/grandmaster.err',
          '/usr/bin/python3','-u',directory+'/peer.py','--seconds',str(seconds),
          '--serial',settings['peer_serial'],'--mac',settings['peer_mac'],
          '--status',directory+'/status.json']
    return shlex.join(args)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','status','stop'])
    parser.add_argument('--config',default='config.local.json')
    parser.add_argument('--seconds',type=int,default=0)
    args=parser.parse_args()
    if args.seconds<0 or args.seconds>3600 or 0<args.seconds<10:
        parser.error('seconds must be 0 or 10..3600')
    settings=load_config(args.config);host=settings['peer_host']
    if args.action=='start':
        dos(settings,'preflight')
        if remote(host,'systemctl --user is-active --quiet ptp4d-gm',check=False).returncode==0:
            raise RuntimeError('Grandmaster is already running. Use status or stop first.')
        remote(host,peer_start_command(settings,args.seconds+20 if args.seconds else 0))
        try: result=dos(settings,'start',args.seconds)
        except BaseException:
            remote(host,'systemctl --user stop ptp4d-gm',check=False);raise
        print(result['screen']['text'])
        print('PTP4D started. Use status to inspect offsets; stop returns DOS to its prompt.')
    elif args.action=='status':
        print(remote(host,'systemctl --user is-active ptp4d-gm; cat '+
                     shlex.quote(settings['peer_dir']+'/status.json'),check=False).stdout)
        print(dos(settings,'status')['text'])
    else:
        result=dos(settings,'stop')
        remote(host,'systemctl --user stop ptp4d-gm',check=False)
        print(result.get('screen',result)['text'])
        print(remote(host,'cat '+shlex.quote(settings['peer_dir']+'/status.json')).stdout)
if __name__=='__main__':
    try: main()
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
