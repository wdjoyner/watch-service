"""Where a caliber's files live, and its settings (calibers/<slug>/caliber.yaml).

    import caliber
    d = caliber.folder('6497')            # .../calibers/6497
    cfg = caliber.load(d)                 # caliber.yaml as a dict
    cfg['name'], cfg['slug'], caliber.variant_flag(cfg)

Each caliber has its own folder with its fact files (steps, assembly, parts), its
credits.yaml and caliber.yaml. Drawings extracted from your own SWF (parts/,
parts_assembly/) and rendered images (assets/) are written there too, and are ignored
by git.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = '6497'


def folder(slug=None):
    return os.path.join(ROOT, 'calibers', slug or os.environ.get('CALIBER') or DEFAULT)


def available():
    base = os.path.join(ROOT, 'calibers')
    return sorted(d for d in os.listdir(base) if os.path.exists(os.path.join(base, d, 'caliber.yaml')))


def load(path):
    """caliber.yaml from a caliber folder (or the path of the file itself)"""
    import yaml
    f = path if path.endswith('.yaml') else os.path.join(path, 'caliber.yaml')
    if not os.path.exists(f):
        raise SystemExit(f'{f} is missing: every caliber folder needs a caliber.yaml '
                         f'(known calibers: {", ".join(available())})')
    return yaml.safe_load(open(f, encoding='utf-8'))


def variant_flag(cfg):
    """name of the per-step flag that marks parts differing between variants (or None)"""
    return cfg.get('variant_flag')
