"""TG Drive: a Google-Drive-style file manager on top of a Telegram user account."""
import os as _os

# numpy's maths libraries start one thread per CPU core for every matrix operation. TG Drive's are small
# and run in the background, where that only makes every core busy at once: one thread each is plenty.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
             "VECLIB_MAXIMUM_THREADS", "RAYON_NUM_THREADS", "TOKENIZERS_PARALLELISM"):
    _os.environ.setdefault(_var, "false" if _var == "TOKENIZERS_PARALLELISM" else "1")

__version__ = "2.4.0"
