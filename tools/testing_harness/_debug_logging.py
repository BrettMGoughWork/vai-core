"""Debug: capture what the log functions actually write to stdout."""
import sys
import io
from src.platform.runtime.job import create_job
from src.platform.transport.normalization import ChannelMessage
from src.platform.observability.logging import log_job_created, log_job_started, log_job_finished

ch = ChannelMessage(input={"x": 1})
job = create_job(ch)
print("job_id:", job.job_id)

old = sys.stdout
sys.stdout = buf = io.StringIO()
try:
    log_job_created(job)
    log_job_started(job)
    log_job_finished(job)
    output = buf.getvalue()
    print("raw output:", repr(output))
    lines = [l for l in output.split("\n") if l.strip()]
    print(f"lines: {len(lines)}")
    for i, l in enumerate(lines):
        print(f"  line {i}: {repr(l)}")
        print(f"    [S4] in line: {'[S4]' in l}")
finally:
    sys.stdout = old
