#!/usr/bin/env python3
"""Control a leased TimeStick grandmaster via Linux ALSA or macOS CoreMIDI."""
import argparse, binascii, fcntl, json, pathlib, secrets, signal, struct, time
try:
    from . import midi_transport
except ImportError:
    import midi_transport

def u(b, at, n=4): return int.from_bytes(b[at:at+n], 'little')
def frame(raw):
    raw += struct.pack('<H', binascii.crc_hqx(raw, 0xffff))
    return b'\xf0\x7dTSK\x03\x20' + bytes(v for b in raw for v in (b & 127, b >> 7)) + b'\xf7'

class Framer:
    def __init__(self): self.pending=bytearray()
    def feed(self, data):
        for b in data:
            if b>=0xf8: continue
            if b==0xf0: self.pending=bytearray([b]); continue
            if not self.pending: continue
            if len(self.pending)>=848 or (b>=128 and b!=0xf7): self.pending.clear(); continue
            self.pending.append(b)
            if b!=0xf7: continue
            f=bytes(self.pending); self.pending.clear()
            if len(f)<12 or len(f)%2 or f[:5]!=b'\xf0\x7dTSK': continue
            pairs=f[7:-1]
            if any(pairs[i]>127 or pairs[i+1]>1 for i in range(0,len(pairs),2)): continue
            raw=bytes(pairs[i]|pairs[i+1]<<7 for i in range(0,len(pairs),2))
            if binascii.crc_hqx(raw[:-2],0xffff)!=u(raw,len(raw)-2,2): continue
            yield f[5],f[6],raw[:-2]

class Peer:
    def __init__(self,args,transport=None):
        self.args=args
        self.passive=bool(getattr(args,'passive',0))
        self.transport=transport or midi_transport.open_transport(
            args.serial,getattr(args,'transport','auto'),receive_only=self.passive)
        self.parser=Framer(); self.nonce=secrets.randbits(32) or 1; self.seq=0
        self.mac=bytes.fromhex(args.mac.replace(':','')); self.generation=0; self.started=False
        self.stop_requested=False; self.state={'serial':args.serial,'role':'grandmaster','domain':42}
        self.last_print=0;self.identity_seen=False;self.valid_frames=0;self.last_flags=None
    def emit(self,event,**items):
        row={'event':event,'unix_time':time.time(),**items}; print(json.dumps(row),flush=True)
        self.state.update(row)
        if self.args.status:
            p=pathlib.Path(self.args.status); p.parent.mkdir(parents=True,exist_ok=True)
            q=p.with_suffix('.tmp');q.write_text(json.dumps(self.state,indent=2)+'\n');q.replace(p)
    def pump(self,timeout):
        data=self.transport.read(timeout); frames=list(self.parser.feed(data))
        for version,kind,b in frames:
            if len(b)==94 and (version,kind) in ((2,0x10),(3,0x22)) and b[11]==42:
                if b[4:10]!=self.mac:
                    raise RuntimeError('Selected USB device telemetry does not match the requested MAC')
                self.valid_frames+=1;self.last_flags=b[10]
                if not self.identity_seen:
                    self.identity_seen=True
                    self.emit('identity',mac=self.mac.hex(':'),flags=b[10],generation=u(b,12))
                if version==3 and kind==0x22:
                    gm=dict(flags=b[10],generation=u(b,12),seconds=u(b,16,6),nanos=u(b,22),syncs=u(b,50),followups=u(b,54),delay_requests=u(b,58),delay_responses=u(b,62),timestamp_errors=u(b,70),sync_sequence=u(b,26,2),delay_sequence=u(b,28,2),t1=[u(b,30,6),u(b,36)],t4=[u(b,40,6),u(b,46)],phase=b[74],error=u(b,76),restored=b[82],armed=b[83])
                    previous=self.state.get('grandmaster',{})
                    self.state['grandmaster']=gm
                    if gm!=previous or time.monotonic()-self.last_print>=1:
                        self.last_print=time.monotonic();self.emit('telemetry',grandmaster=gm)
        return frames
    def command(self,op,extended=False,value=0):
        if self.passive: raise PermissionError('Passive mode sends no commands')
        if op not in (1,2,3,4,5): raise ValueError('Unsupported operation')
        self.seq+=1
        raw=struct.pack('<IIBBBBI6s',self.nonce,self.seq,op,2,42,int(extended),value,self.mac)
        data=frame(raw); end=time.monotonic()+3
        self.transport.write(data,max(0,end-time.monotonic()))
        while time.monotonic()<end:
            for version,kind,b in self.pump(.1):
                if version==3 and kind==0x21 and len(b)==32 and u(b,0)==self.nonce and u(b,4)==self.seq and b[8]==op and b[22:28]==self.mac and b[28]==42:
                    ack=dict(operation=op,result=b[9],phase=b[10],profile=b[11],error=u(b,12),generation=u(b,16),remaining=u(b,20,2),capabilities=b[29],restored=b[30],armed=b[31])
                    self.emit('ack',ack=ack)
                    if b[9]: raise RuntimeError(f'Command rejected: {ack}')
                    return ack
        raise TimeoutError(f'Missing correlated ACK for operation {op}')
    def run(self):
        try:
            self.emit('opened',device=self.transport.description,mac=self.mac.hex(':'),passive=self.passive)
            if self.passive:
                end=time.monotonic()+self.args.passive
                while not self.stop_requested and time.monotonic()<end:
                    self.pump(min(.2,max(0,end-time.monotonic())))
                if not self.identity_seen:
                    raise RuntimeError('No CRC-valid telemetry from the selected TimeStick')
                self.emit('passive_complete',valid_frames=self.valid_frames,flags=self.last_flags,commands_sent=0)
                return
            end=time.monotonic()+2
            while not self.identity_seen and not self.stop_requested and time.monotonic()<end:
                self.pump(.1)
            if self.stop_requested: return
            if not self.identity_seen:
                raise RuntimeError('No CRC-valid identity telemetry; no commands sent')
            a=self.command(1,True)
            if a['armed']: raise RuntimeError('Existing timing session is active')
            if a['error']==2 and a['restored']: a=self.command(3)
            if a['error'] or not a['restored'] or a['capabilities']&31!=31: raise RuntimeError(f'Not ready: {a}')
            a=self.command(5,value=4)
            if a['error'] or a['armed'] or not a['restored'] or a['capabilities']&63!=63 or a['remaining']!=4:
                raise RuntimeError(f'4 Hz rate not acknowledged: {a}')
            if self.stop_requested: return
            # Mark ownership before START so a missing ACK still triggers STOP.
            self.started=True;a=self.command(2,True,15);self.generation=a['generation']
            if a['error'] or not a['armed'] or a['profile']!=2 or not self.generation: raise RuntimeError(f'Start not armed: {a}')
            begin=renew=time.monotonic();self.emit('started',generation=self.generation)
            while not self.stop_requested and (not self.args.seconds or time.monotonic()-begin<self.args.seconds):
                self.pump(.2)
                gm=self.state.get('grandmaster',{})
                if gm.get('generation')==self.generation and (gm.get('error') or gm.get('phase')==9): raise RuntimeError(f'Grandmaster stopped: {gm}')
                if time.monotonic()-renew>=5:
                    a=self.command(4,True,self.generation);renew=time.monotonic()
                    if a['error'] or a['profile']!=2 or a['generation']!=self.generation or not a['armed']: raise RuntimeError(f'Lease not renewed: {a}')
        finally:
            try:
                if self.started:
                    a=self.command(3)
                    if a['error'] or a['armed'] or not a['restored'] or a['profile']!=2 or (self.generation and a['generation']!=self.generation): raise RuntimeError(f'Stop not restored: {a}')
                    self.emit('stopped',restoration_verified=True)
            finally: self.transport.close()

def mac_address(value):
    try:
        compact=value.replace(':','')
        if len(compact)!=12 or any(c not in '0123456789abcdefABCDEF' for c in compact): raise ValueError
        raw=bytes.fromhex(compact)
        if raw[0]&1 or not any(raw): raise ValueError
    except ValueError: raise argparse.ArgumentTypeError('Expected a nonzero unicast MAC address')
    return raw.hex(':')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial',help='Exact TimeStick USB serial; never selected by display name')
    p.add_argument('--mac',type=mac_address,help='Expected TimeStick MAC, checked against CRC-valid telemetry')
    p.add_argument('--transport',choices=('auto','alsa','coremidi'),default='auto')
    p.add_argument('--seconds',type=int,default=120,help='GM duration, 0 until Ctrl+C (default: 120)')
    p.add_argument('--status',help='Write JSON status to this path')
    p.add_argument('--list',action='store_true',help='List online matching USB MIDI devices; no commands')
    p.add_argument('--passive',type=int,metavar='SECONDS',help='Receive only for 1..60 seconds; no output port or commands')
    a=p.parse_args(argv)
    if a.seconds<0: p.error('seconds must be nonnegative')
    if a.passive is not None and not 1<=a.passive<=60: p.error('passive duration must be 1..60')
    if a.list:
        if a.passive is not None or a.serial or a.mac or a.status:
            p.error('--list cannot be combined with session options')
        print(json.dumps(midi_transport.devices(a.transport),indent=2));return
    if not a.serial or not a.mac: p.error('--serial and --mac are required for a session')
    # Preserve the existing lock shared by all peer.py instances on this host.
    lock=pathlib.Path.home()/'.cache/ptp4d/peer.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        peer=Peer(a)
        def stop(*_): peer.stop_requested=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        peer.run()
if __name__=='__main__': main()
