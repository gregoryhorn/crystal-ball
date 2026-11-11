import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from crystal_ball.senses import see as fs


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.media = self.base / 'media'
        self.media.mkdir()
        self.model = SimpleNamespace(config=SimpleNamespace(projection_dim=7))
        for mocker in (
            patch.object(fs, 'CACHE', str(self.base / 'cache')),
            patch.object(fs, 'load_model', return_value=(self.model, None, 'cpu')),
            patch.object(fs, 'embed_images', side_effect=lambda m, p, d, paths: np.ones((len(paths), m.config.projection_dim), dtype='float32')),
            patch.object(fs, 'extract', side_effect=self.extract),
        ):
            mocker.start()
            self.addCleanup(mocker.stop)

    def extract(self, path, outdir, every, cap, mode):
        frame = Path(outdir) / 'frame.jpg'
        frame.write_bytes(b'stub frame')
        return [(0., str(frame))]

    def file(self, name):
        path = self.media / name
        path.write_bytes(b'stub media')
        return path

    def args(self, *paths, **kwargs):
        return SimpleNamespace(paths=list(map(str, paths)), model='large', every=2., cap=60, mode='interval', **kwargs)

    def index(self, *paths):
        self.assertEqual(fs.cmd_index(self.args(*paths)), 0)
        return fs.load_index(str(self.idir()))

    def idir(self):
        return Path(fs.CACHE) / fs.key_for(str(self.media))[0]

    def test_partial_update_preserves_siblings_until_directory_reconciliation(self):
        a, b = self.file('a.mp4'), self.file('b.mp4')
        initial = self.index(self.media)
        b.unlink()
        a.write_bytes(b'changed media')
        updated = self.index(a)
        self.assertEqual(set(updated['files']), {str(a), str(b)})
        np.testing.assert_array_equal(updated['emb'], np.ones((2, 7)))
        self.assertEqual(updated['frames'][0], initial['frames'][1])
        reconciled = self.index(self.media)
        self.assertEqual(set(reconciled['files']), {str(a)})

    def test_empty_scan_replaces_stale_index_and_removes_thumbs(self):
        a = self.file('a.mp4')
        old = self.index(self.media)
        a.unlink()
        new = self.index(self.media)
        self.assertEqual(new['files'], {})
        self.assertEqual(new['frames'], [])
        self.assertEqual(new['emb'].shape, (0, 7))
        self.assertFalse(Path(old['frames'][0]['thumb']).exists())

    def test_fresh_empty_directory_has_model_dimension(self):
        self.assertEqual(self.index(self.media)['emb'].shape, (0, 7))

    def test_partial_model_change_preserves_existing_index(self):
        a, b = self.file('a.mp4'), self.file('b.mp4')
        old = self.index(self.media)
        b.unlink()
        args = self.args(a)
        args.model = 'base'
        self.model.config.projection_dim = 3
        self.assertEqual(fs.cmd_index(args), 2)
        new = fs.load_index(str(self.idir()))
        self.assertEqual(new['files'], old['files'])
        self.assertEqual(new['model'], old['model'])
        np.testing.assert_array_equal(new['emb'], old['emb'])
        args.paths = [str(self.media)]
        self.assertEqual(fs.cmd_index(args), 0)
        rebuilt = fs.load_index(str(self.idir()))
        self.assertEqual(set(rebuilt['files']), {str(a)})
        self.assertEqual(rebuilt['emb'].shape, (1, 3))

    def test_metadata_failure_preserves_committed_embeddings_and_thumbs(self):
        a = self.file('a.mp4')
        old = self.index(self.media)
        old_bytes = (self.idir() / 'meta.json').read_bytes()
        a.write_bytes(b'changed media')
        replace = fs.os.replace
        def fail_metadata(src, dst):
            if str(dst).endswith('meta.json'):
                raise OSError('commit failed')
            return replace(src, dst)
        with patch.object(fs.os, 'replace', side_effect=fail_metadata):
            with self.assertRaisesRegex(OSError, 'commit failed'):
                self.index(self.media)
        self.assertEqual((self.idir() / 'meta.json').read_bytes(), old_bytes)
        np.testing.assert_array_equal(fs.load_index(str(self.idir()))['emb'], old['emb'])
        self.assertTrue(Path(old['frames'][0]['thumb']).exists())
        self.assertFalse(list(self.idir().glob('*.tmp')))

    def test_embedding_replace_failure_preserves_previous_index(self):
        self.file('a.mp4')
        old = self.index(self.media)
        with patch.object(fs.os, 'replace', side_effect=OSError('emb failed')):
            with self.assertRaises(OSError):
                fs.save_index(str(self.idir()), {'frames': []}, np.zeros((0, 7)))
        np.testing.assert_array_equal(fs.load_index(str(self.idir()))['emb'], old['emb'])
        self.assertFalse(list(self.idir().glob('*.tmp')))

    def test_metadata_commit_references_complete_new_generation(self):
        a = self.file('a.mp4')
        old = self.index(self.media)
        a.write_bytes(b'changed media')
        replace = fs.os.replace
        def inspect_commit(src, dst):
            if str(dst).endswith('meta.json'):
                meta = json.loads(Path(src).read_text())
                self.assertNotEqual(meta['emb_file'], old['emb_file'])
                self.assertEqual(np.load(self.idir() / meta['emb_file']).shape, (1, 7))
                self.assertTrue(Path(old['frames'][0]['thumb']).exists())
            return replace(src, dst)
        with patch.object(fs.os, 'replace', side_effect=inspect_commit):
            new = self.index(self.media)
        self.assertTrue(Path(new['frames'][0]['thumb']).exists())
        self.assertFalse(Path(old['frames'][0]['thumb']).exists())

    def test_legacy_index_loads(self):
        self.idir().mkdir(parents=True)
        np.save(self.idir() / 'emb.npy', np.ones((1, 7)))
        (self.idir() / 'meta.json').write_text(json.dumps({'frames': [{}]}))
        self.assertEqual(fs.load_index(str(self.idir()))['emb'].shape, (1, 7))

    def test_empty_wrong_dimension_index_is_skipped_during_query(self):
        self.file('a.mp4')
        self.index(self.media)
        fs.save_index(str(Path(fs.CACHE) / 'empty'),
                      {'root': str(self.media), 'model': fs.model_id('large'), 'files': {}, 'frames': []}, np.zeros((0, 512)))
        args = SimpleNamespace(model='large', dir=None, image=None, text='test', top=10, gap=4., json=True)
        with patch.object(fs, 'embed_text', return_value=np.ones(7)), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fs.cmd_query(args), 0)
        self.assertEqual(len(json.loads(out.getvalue())), 1)

    def test_only_empty_index_does_not_load_model(self):
        self.index(self.media)
        args = SimpleNamespace(model='large', dir=None)
        with patch.object(fs, 'load_model') as load:
            self.assertEqual(fs.cmd_query(args), 1)
            load.assert_not_called()

    def test_heif_without_decoder_warns_and_never_extracts_video(self):
        for ext in ('HEIC', 'heif'):
            self.file('image.' + ext)
        with patch.dict(sys.modules, {'pillow_heif': None}), patch.object(fs, 'extract') as extract, contextlib.redirect_stderr(io.StringIO()) as err:
            new = self.index(self.media)
        extract.assert_not_called()
        self.assertEqual(new['files'], {})
        self.assertIn('pillow_heif decoder unavailable', err.getvalue())
        self.assertEqual(err.getvalue().count('skip HEIC/HEIF'), 2)

    def test_heif_with_decoder_uses_image_path(self):
        from PIL import Image
        path = self.media / 'image.heic'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=4x4','-frames:v','1','-threads','1','-f','image2','-c:v','png',str(path)],check=True,capture_output=True)
        decoder = SimpleNamespace(register_heif_opener=unittest.mock.Mock())
        with patch.dict(sys.modules, {'pillow_heif': decoder}), patch.object(fs, 'extract') as extract:
            new = self.index(self.media)
        decoder.register_heif_opener.assert_called_once()
        extract.assert_not_called()
        self.assertEqual(len(new['frames']), 1)

    def test_nonpositive_and_nonfinite_sampling_is_rejected(self):
        for field, value in [('cap', 0), ('cap', -1), ('every', 0), ('every', -1), ('every', float('nan')), ('every', float('inf'))]:
            with self.subTest(field=field, value=value):
                args = self.args(self.media)
                setattr(args, field, value)
                with patch.object(fs, 'collect') as collect:
                    self.assertEqual(fs.cmd_index(args), 2)
                    collect.assert_not_called()

    def test_per_file_oserrors_warn_and_continue(self):
        bad, good = self.file('a.mp4'), self.file('b.mp4')
        for stage in ('stat', 'extract', 'embed', 'copy'):
            with self.subTest(stage=stage):
                # Each run starts with a fresh cache so both files are processed.
                with patch.object(fs, 'CACHE', str(self.base / stage)):
                    if stage == 'stat':
                        original = fs.os.stat
                        def stat(path, *a, **kw):
                            if str(path) == str(bad):
                                raise OSError('stat denied')
                            return original(path, *a, **kw)
                        mocker = patch.object(fs.os, 'stat', side_effect=stat)
                    else:
                        name = {'extract': 'extract', 'embed': 'embed_images', 'copy': 'shutil.copyfile'}[stage]
                        target, attr = (fs.shutil, 'copyfile') if stage == 'copy' else (fs, name)
                        original = getattr(target, attr)
                        calls = [0]
                        def fail_first(*a, **kw):
                            calls[0] += 1
                            if calls[0] == 1:
                                raise OSError(stage + ' denied')
                            return original(*a, **kw)
                        mocker = patch.object(target, attr, side_effect=fail_first)
                    with mocker, contextlib.redirect_stderr(io.StringIO()) as err:
                        new = self.index(self.media)
                    self.assertEqual(set(new['files']), {str(good)})
                    self.assertEqual(new['emb'].shape, (1, 7))
                    self.assertIn('skip file', err.getvalue())


class WhisperTests(unittest.TestCase):
    def args(self, flags, output=None):
        from crystal_ball.senses.hear import whispercpp_args
        cfg={'whispercpp':{'bin':'whisper-cli','model':'model.bin'}}
        return whispercpp_args(cfg,'input.wav',output,flags)

    def test_output_formats_require_explicit_output_path(self):
        for flag in ['-otxt','-osrt','-ovtt','-ojson','-olrc','-owts','-ocsv','-oj','-ojf','--output-txt','--output-srt','--output-vtt','--output-json','--output-json-full','--output-lrc','--output-words','--output-csv']:
            with self.assertRaisesRegex(ValueError,'require -of'):
                self.args([flag])

    def test_output_path_and_defaults_and_model_override_are_forwarded(self):
        args=self.args(['-ojf'],'output file')
        self.assertEqual(args,['whisper-cli','-m','model.bin','-f','input.wav','-ojf','-of','output file'])

    def test_no_output_format_still_works(self):
        self.assertEqual(self.args([]),['whisper-cli','-m','model.bin','-f','input.wav'])

    def test_missing_or_empty_output_path_is_rejected(self):
        for output in (None,''):
            with self.assertRaises(ValueError):
                self.args(['-ojf'],output)
