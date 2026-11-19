# Third-party components

This package is a local Windows tool distribution. Source game assets are not included in the portable distribution.

- DSAnimStudio — Meowmaritus, MIT; reference commit 6a2be66278e3b49362fcedda016eefab73b98935. License in licenses/DSAS.
- SoulsFormats / SoulsAssetPipeline — installed DSAS distribution; respective upstream license terms apply.
- Avalonia 11.2.3 — MIT; https://github.com/AvaloniaUI/Avalonia
- .NET 9.0.11 — Microsoft and contributors, MIT; original runtime license and third-party notices in licenses/dotnet-9.0.11.
- MonoGame, Havoc, SharpDX, AssimpNet, TexImpNet and transitive dependencies — supplied license notices in licenses/DSAS.
- Oodle native decoder — copied from the existing local DSAS toolchain; proprietary component, not covered by this project's MIT license.
- Blender 4.5.5 — bundled portable distribution; GPL-2.0-or-later, with upstream notices in runtime/blender/license and copyright.txt. Source: https://download.blender.org/source/ .
- Python 3.11.11, NumPy 1.26.4, Pillow 12.2.0 — bundled with Blender/Python; original licenses/dist-info retained.
- FFmpeg 2025-02-24 git-6232f416b1 full build (gyan.dev) — GPL build; runtime/ffmpeg/LICENSE and README.txt retained. Build/source information: https://www.gyan.dev/ffmpeg/builds/ and https://git.ffmpeg.org/gitweb/ffmpeg.git/commit/6232f416b1 .
- FMOD Ex/Event 64-bit — bundled from the local DSAS RC6.1 toolchain; proprietary runtime, not covered by this project's MIT license. Upstream terms apply.
- Original component licenses are not replaced by this project's source-code license.
- Program icon — user-supplied image, not covered by the software source license.
- SourceIO meshoptimizer decoder (pylib.pyd) — REDxEYE, MIT; notice in licenses/SourceIO-MIT.txt. Bundled solely for reading compiled mesh vertex buffers.
- DMX datamodel.py — MIT; original license header retained. SCT changes index UUID/string lookup and round Time values to nearest Source 2 tick.
- CS2 Workshop Tools — external Valve installation, not redistributed in this distribution. The selected addon determines the compiler/resourceinfo installation.

Python affine, event, audio and validation modules adapt the user's existing verified extraction pipeline. Historical reference extracts are retained only with developer test evidence and are attributed to DSAnimStudio.

- miniz 3.0.2 — MIT, Rich Geldreich and contributors; native single-EXE ZIP reader. License in licenses/miniz-LICENSE.txt; source: https://github.com/richgel999/miniz/tree/3.0.2 .
