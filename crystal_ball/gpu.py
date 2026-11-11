"""Conservative local GPU admission, shared by GPU-capable senses."""
import subprocess


def admit(required_gb=3.5, torch=None):
    """Return (device, reason). Unknown free memory means CPU admission."""
    free=None
    if torch is not None and not torch.cuda.is_available():
        return 'cpu','CUDA unavailable; CPU selected'
    try:
        if torch is not None and torch.cuda.is_available():
            free=torch.cuda.mem_get_info(0)[0]/2**30
        else:
            result=subprocess.run(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits','--id=0'],capture_output=True,text=True,check=True,timeout=5)
            free=float(result.stdout.strip().splitlines()[0])/1024
    except (OSError,ValueError,IndexError,subprocess.SubprocessError):
        pass
    if free is None:
        return 'cpu','free VRAM unavailable; CPU selected'
    if free<float(required_gb):
        return 'cpu',f'free VRAM {free:.2f} GiB below required {float(required_gb):.2f} GiB'
    return 'cuda',None


def is_oom(exc):
    message=str(exc).lower()
    return 'out of memory' in message or 'cuda_error_out_of_memory' in message or 'cuda out of memory' in message
