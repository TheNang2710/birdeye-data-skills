"""Package shim for the bundled CLI modules.

The proprietary ML runtime (``junk_ml``, ``trending_score`` + ``lr_params.json``)
is kept in the secure ``api/_ml/`` folder instead of this generic bundle.
Appending that folder to ``__path__`` keeps the existing
``from modules import junk_ml`` imports working unchanged.
"""
import pathlib

_ML_DIR = pathlib.Path(__file__).resolve().parents[3] / "_ml"  # api/_ml
if _ML_DIR.is_dir():
    __path__.append(str(_ML_DIR))
