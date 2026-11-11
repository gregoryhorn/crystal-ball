# Third-party notices

Crystal Ball vendors only the signal QC dependency closure from ffmpeg-skill:
`qc.py`, `check.py`, `_platforms.py`, and the shared runner, probe, emission,
decision, color and font/drawtext helpers. The `_common` facade is reduced to
exports required by QC. The optional vendor contact-sheet font constant and
cache default are adapted; Crystal Ball supplies its own shared review frames.
All upstream source remains covered by the following notice.

## ffmpeg-skill — MIT

MIT License

Copyright (c) 2026 kajisho5

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Separately installed runtime dependencies and models

Models are downloaded by the user and are **not bundled**. Crystal Ball's
normal actions use local-only model loading. `setup` prints user-run steps;
`doctor` never downloads. Review the licences of your chosen replacement
models and endpoint services before distributing them.

| Component | Licence | Distribution here |
|---|---|---|
| faster-whisper | MIT | Requirement only |
| OpenAI Whisper weights, including large-v3-turbo | MIT | Not bundled |
| CTranslate2 | MIT | Requirement only |
| OpenAI CLIP code and ViT-L/14 weights | MIT | Not bundled |
| transformers | Apache-2.0 | Requirement only |
| huggingface-hub, tokenizers, safetensors | Apache-2.0 | Requirements only |
| torch | BSD-3-Clause | Requirement only |
| NumPy | BSD-3-Clause | Requirement only |
| Pillow | HPND and upstream component notices | Requirement only |
| Tesseract and tessdata / tessdata_best | Apache-2.0 | Separate binary and user-selected traineddata |
| ffmpeg / ffprobe | LGPL-2.1-or-later or GPL-2.0-or-later, depending on build options | Separately installed binaries; not bundled or linked into this package |
| whisper.cpp | MIT (check linked binary components) | Optional, separately installed binary |
| demucs | MIT | Optional, separately installed command |
| PyAV | BSD-3-Clause; linked FFmpeg has its own terms | Present in the hear environment; deliberately bypassed for decoding |
| NVIDIA CUDA/cuDNN/cuBLAS components | NVIDIA proprietary redistribution terms | User-installed engine environment only |
| pytest | MIT | Development/test requirement only |

Torch's and Pillow's distributions carry additional third-party notices.
Pinned environments include transitive dependencies under their own licences;
these files describe installation inputs, not a redistribution of their code.
Hermes auxiliary routing is provided by the separately installed Hermes host.
No provider credentials, media, model weights, traineddata or GPU libraries
are included in this repository or its wheel.
