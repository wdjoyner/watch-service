"""Smoke test: build disassembly step 4 at 480p with the generated (publishable) art.

    python tests/smoke_test.py

Needs no SWF. Checks that the assets are written and that Manim produces a video.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, **kw):
    print('$', ' '.join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def main():
    run([sys.executable, '-I', 'tools/prep_assets.py', '--art', 'simple', '.', '4'])
    for f in ('step04_bg.png', 'step04_part.png', 'step04_part.json'):
        assert os.path.exists(os.path.join(ROOT, 'assets', 'simple', f)), f'missing assets/simple/{f}'
    media = tempfile.mkdtemp(prefix='smoke_')
    try:
        env = dict(os.environ, ART='simple', STEP='4')
        run([sys.executable, '-m', 'manim', '-ql', '--media_dir', media, '-o', 'smoke_step04',
             'swisslab_step.py', 'DisassemblyStep'], env=env)
        videos = [os.path.join(d, f) for d, _, fs in os.walk(media) for f in fs if f == 'smoke_step04.mp4']
        assert videos and os.path.getsize(videos[0]) > 10_000, 'no video written'
        print('OK:', videos[0], os.path.getsize(videos[0]), 'bytes')
    finally:
        shutil.rmtree(media, ignore_errors=True)


if __name__ == '__main__':
    main()
