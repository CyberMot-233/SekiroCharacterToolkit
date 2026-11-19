param([Parameter(Mandatory=$true)][string]$InstalledDirectory)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$App=(Resolve-Path -LiteralPath $InstalledDirectory).Path
if(-not(Test-Path -LiteralPath (Join-Path $App 'runtime/worker/CharacterWorker.exe'))){
 $Candidates=@(Get-ChildItem -LiteralPath (Join-Path $App 'app') -Directory -ErrorAction SilentlyContinue | Where-Object {Test-Path -LiteralPath (Join-Path $_.FullName 'runtime/worker/CharacterWorker.exe')})
 if($Candidates.Count -ne 1){throw '请指定完整的 app/版本目录，避免混用多个版本。'}
 $App=$Candidates[0].FullName
}
foreach($File in @('runtime/blender/blender.exe','runtime/worker/CharacterWorker.exe','runtime/ffmpeg/ffmpeg.exe','scripts/vendor/sourceio_mesh/pylib.pyd')){
 if(-not(Test-Path -LiteralPath (Join-Path $App $File))){throw "缺少运行组件：$File"}
}
if([IO.Path]::GetFullPath($Root) -eq [IO.Path]::GetFullPath($App)){throw '来源目录不能与源码目录相同。'}
$Runtime=Join-Path $Root 'runtime'
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
Get-ChildItem -LiteralPath (Join-Path $App 'runtime') -Force | ForEach-Object {
 Copy-Item -LiteralPath $_.FullName -Destination $Runtime -Recurse -Force
}
$Lib=Join-Path $Root 'src/CharacterWorker/lib'
New-Item -ItemType Directory -Force -Path $Lib | Out-Null
foreach($Name in @('AssimpNet.dll','DrSwizzler.dll','Havoc.dll','MonoGame.Framework.dll','oo2core_6_win64.dll','SharpDX.Direct3D11.dll','SharpDX.dll','SharpDX.DXGI.dll','SharpDX.MediaFoundation.dll','SharpDX.XAudio2.dll','SharpDX.XInput.dll','SoulsAssetPipeline.dll','SoulsFormats.dll','StbImageSharp.dll','StbImageWriteSharp.dll','TeximpNet.dll','ZstdNet.dll')){
 Copy-Item -LiteralPath (Join-Path $App "runtime/worker/$Name") -Destination (Join-Path $Lib $Name) -Force
}
Copy-Item -LiteralPath (Join-Path $App 'scripts/vendor/sourceio_mesh/pylib.pyd') -Destination (Join-Path $Root 'scripts/vendor/sourceio_mesh/pylib.pyd') -Force
Write-Host '运行组件已恢复。runtime、DLL 和 PYD 均被 .gitignore 排除。'
