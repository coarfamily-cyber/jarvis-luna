import socket
_original=socket.socket.connect
_original_ex=socket.socket.connect_ex
def _allowed(address):
    return isinstance(address,tuple) and address and address[0] in ('127.0.0.1','::1','localhost')
def _connect(self,address):
    if not _allowed(address):raise RuntimeError('External network blocked for offline verification')
    return _original(self,address)
def _connect_ex(self,address):
    if not _allowed(address):raise RuntimeError('External network blocked for offline verification')
    return _original_ex(self,address)
socket.socket.connect=_connect
socket.socket.connect_ex=_connect_ex
# Keep the same deny policy even when a Python test supplies a minimal child env.
import subprocess, os
_popen=subprocess.Popen
class _OfflinePopen(_popen):
    def __init__(self,*args,**kwargs):
        if kwargs.get('env') is not None:
            env=dict(kwargs['env']);policy=os.path.dirname(__file__)
            env['PYTHONPATH']=policy+os.pathsep+env.get('PYTHONPATH','')
            kwargs['env']=env
        super().__init__(*args,**kwargs)
subprocess.Popen=_OfflinePopen
