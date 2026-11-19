param([string]$BuildTemp=(Join-Path $PSScriptRoot '../../cache/launcher_build'))
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force -Path $BuildTemp | Out-Null
$env:TEMP=$BuildTemp;$env:TMP=$BuildTemp
Push-Location $PSScriptRoot
try {
    # MinGW 16 adds a default manifest. Remove it to keep our explicit asInvoker manifest.
    $specs=(& gcc -dumpspecs | Out-String).Replace('%{!shared:%:if-exists(default-manifest.o%s)}','')
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'launcher.specs'),$specs)
    windres launcher.rc -O coff -o launcher-res.o
    if($LASTEXITCODE){throw 'Resource build failed'}
    gcc -O2 -DMINIZ_NO_ARCHIVE_WRITING_APIS -DMINIZ_NO_ZLIB_COMPATIBLE_NAMES -c vendor/miniz/miniz.c vendor/miniz/miniz_tinfl.c vendor/miniz/miniz_tdef.c vendor/miniz/miniz_zip.c
    if($LASTEXITCODE){throw 'ZIP reader build failed'}
    g++ "-specs=launcher.specs" -std=c++17 -O2 -static -municode -mwindows launcher.cpp miniz.o miniz_tinfl.o miniz_tdef.o miniz_zip.o launcher-res.o -o launcher.exe -lbcrypt -lole32 -lshell32 -luuid -lcomctl32 -lgdi32
    if($LASTEXITCODE){throw 'Launcher build failed'}
} finally {Pop-Location}
